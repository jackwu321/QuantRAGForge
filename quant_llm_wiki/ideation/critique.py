"""批判步：确定性反向 query + 检索证据 + LLM 有据批判（设计 D3）。

红队立场但证据先行：批判必须引用编号证据；无证据时降级为
grounded=False 并显式标注——与 wiki_grounded 哲学一致，绝不静默。
"""
from __future__ import annotations

import json
import re
from typing import Callable

from quant_llm_wiki.ideation.models import CandidateIdea, Critique, Evidence
from quant_llm_wiki.query.rethink import BrainstormIdea

_SEVERITIES = ("fatal", "major", "minor")

CRITIQUE_SYSTEM_PROMPT = """你是量化投研红队评审，任务是攻击候选策略想法。
规则：
- 只能引用给定编号证据（[E1]、[E2]…）支撑批判；每条批判在 evidence_indexes 列出引用的证据编号
- severity 定级：证据表明同类想法已被回测证伪 → fatal；证据指出明确失效场景/结构性风险 → major；其余 → minor
- 不编造证据、不编造回测结果
返回严格 JSON 数组，每条：
{"attack_query": "对应的攻击角度", "text": "批判正文（引用 [En]）", "severity": "fatal|major|minor", "evidence_indexes": [1]}
只返回 JSON，不要 markdown 代码块。"""

_UNGROUNDED_NOTE = """注意：知识库无反例证据（检索无命中）。你可以基于常识给至多 1 条批判，
severity 只能是 minor 或 major，evidence_indexes 留空 []。这条批判会被标注为"无据推断"。"""


def build_attack_queries(idea: BrainstormIdea) -> list[str]:
    """3 个固定攻击角度的确定性 query（无 LLM：省调用且可测，spec 第 2 节）。"""
    core = idea.core_logic[:120]
    return [
        f"{idea.title} {core} 失效 场景 反例 {idea.what_could_break[:60]}",
        f"{idea.title} {core} 拥挤 容量 交易成本 失效",
        f"{idea.title} 市场状态 依赖 牛市 熊市 震荡 风格切换 风险",
    ]


def _format_evidence(evidence: list[Evidence]) -> str:
    lines = []
    for i, ev in enumerate(evidence, start=1):
        tag = "回测判决" if ev.kind == "verdict" else f"知识块/{ev.block_type}"
        lines.append(f"[E{i}] ({tag}, ref={ev.ref}) {ev.excerpt}")
    return "\n".join(lines)


def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("not a JSON array")
    return data


def critique_candidate(
    cand: CandidateIdea,
    evidence: list[Evidence],
    llm: Callable[[list[dict]], str],
    round_index: int,
) -> list[Critique]:
    idea = cand.idea
    body = (f"候选想法：{idea.title}\n核心逻辑：{idea.core_logic}\n"
            f"新意：{idea.what_is_new}\n自述风险：{idea.what_could_break}")
    if evidence:
        user = f"{body}\n\n证据列表：\n{_format_evidence(evidence)}"
    else:
        user = f"{body}\n\n{_UNGROUNDED_NOTE}"
    try:
        entries = _parse_json_array(llm([
            {"role": "system", "content": CRITIQUE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]))
    except Exception:
        return []

    critiques: list[Critique] = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
            continue
        severity = str(entry.get("severity", "minor"))
        if severity not in _SEVERITIES:
            severity = "minor"
        cited: list[Evidence] = []
        for idx in entry.get("evidence_indexes", []) or []:
            try:
                cited.append(evidence[int(idx) - 1])
            except (ValueError, TypeError, IndexError):
                continue
        grounded = bool(cited)
        if not grounded and severity == "fatal":
            severity = "major"  # 无据批判不允许 fatal（fatal 可致淘汰，须有据）
        critiques.append(Critique(
            attack_query=str(entry.get("attack_query", "")),
            text=str(entry["text"]),
            severity=severity,
            grounded=grounded,
            evidence=cited,
            verdict_ids=[ev.ref for ev in cited if ev.kind == "verdict"],
            round=round_index,
        ))
    return critiques
