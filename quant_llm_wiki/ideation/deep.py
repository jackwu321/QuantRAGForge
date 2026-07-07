"""装配层：把真实检索/LLM/打分接进轮次引擎，并落盘双格式演化日志。

所有降级（verdict 层为空、向量检索退化、handoff 缺失）都写进
EvolutionLog.degraded_notes——显式标注，绝不静默（spec 第 5 节）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quant_llm_wiki.ideation.critique import build_attack_queries, critique_candidate
from quant_llm_wiki.ideation.loop import LoopConfig, RefineOutcome, run_loop
from quant_llm_wiki.ideation.models import CandidateIdea, Critique, Evidence, EvolutionLog
from quant_llm_wiki.paths import resolve_kb_root
from quant_llm_wiki.query.brainstorm import (
    apply_filters,
    build_messages,
    format_context,
    retrieve_blocks,
    slugify,
)
from quant_llm_wiki.query.rethink import (
    _compute_composite,
    check_novelty,
    parse_ideas,
    score_coherence_actionability,
    score_traceability,
)
from quant_llm_wiki.shared import (
    DEFAULT_SOURCE_DIRS,
    KnowledgeBlock,
    call_llm_chat,
    load_notes,
    parse_csv_arg,
)
from quant_llm_wiki.verdicts import list_verdicts, retrieve_similar_verdicts

NOVELTY_PENALTY = 0.15
EVIDENCE_PER_QUERY = 2
VERDICT_TOP_K = 2
FALSIFIED_PROMPT_LIMIT = 5

REFINE_SYSTEM_PROMPT = """你是候选策略想法的提案者，正在做精炼决策。
针对红队批判，三选一：
- revise：吸收批判修改想法（给出修改后的 core_logic，可选修改 what_is_new）
- defend：有据反驳（response 必须引用证据编号 [En]/[Vn]，说明批判为何不成立）
- concede：批判致命且无法回应，认输
返回严格 JSON：{"action": "revise|defend|concede", "revised_core_logic": "", "revised_what_is_new": "", "response": ""}
只返回 JSON，不要 markdown 代码块。"""


@dataclass
class DeepBrainstormResult:
    log: EvolutionLog
    md_path: Path
    json_path: Path

    def summary_text(self) -> str:
        lines = [f"深化脑暴完成：{self.log.query}",
                 f"终止原因：{self.log.stopped_reason}"]
        for note in self.log.degraded_notes:
            lines.append(f"⚠️ 降级：{note}")
        survivors = self.log.survivors()
        if survivors:
            lines.append(f"幸存想法 {len(survivors)} 个：")
            for c in survivors:
                score = f"{c.composite:.2f}" if c.composite is not None else "-"
                lines.append(f"- [{c.cid}] {c.idea.title}（综合分 {score}，"
                             f"经 {len(c.revisions)} 次修订）：{c.idea.core_logic}")
        else:
            lines.append("全灭——各候选死因：")
            for c in self.log.candidates:
                lines.append(f"- [{c.cid}] {c.idea.title}：{c.kill_reason}")
            lines.append("建议：放宽方向或换切入点后重跑。")
        lines.append(f"演化日志：{self.md_path}")
        return "\n".join(lines)


def _load_context_blocks(kb_root, query, top_k, retrieval, source_dir):
    """生成上下文检索（薄封装以便测试 patch）。返回 (blocks, mode, warning)。"""
    source_dirs = parse_csv_arg(source_dir) or list(DEFAULT_SOURCE_DIRS)
    notes = load_notes(kb_root, source_dirs)
    notes = apply_filters(notes, content_type=None, market=None, asset_type=None,
                          strategy_type=None, brainstorm_value=None)
    if not notes:
        return [], "none", "无候选笔记（source/status 过滤后为空）"
    return retrieve_blocks(notes, query, top_k, "brainstorm", retrieval,
                           kb_root / "vector_store", kb_root=kb_root)


def _falsified_directions(kb_root) -> list[str]:
    out = []
    for r in list_verdicts(kb_root):
        if r.verdict in ("被证伪", "暂不成立"):
            out.append(f"{r.direction}（{r.date} 判决：{r.verdict}"
                       + (f"，{r.failure_summary}" if r.failure_summary else "") + "）")
    return out[:FALSIFIED_PROMPT_LIMIT]


def _gather_candidate_evidence(cand: CandidateIdea, kb_root: Path,
                               context_blocks: list[KnowledgeBlock]) -> list[Evidence]:
    """对抗检索：反向 query 打 failure_modes 块 + verdict 层（薄封装以便 patch）。"""
    evidence: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    store = kb_root / "vector_store"
    for attack_query in build_attack_queries(cand.idea):
        for hit in retrieve_similar_verdicts(attack_query, store, top_k=VERDICT_TOP_K):
            key = ("verdict", hit["id"])
            if key in seen or hit["verdict"] == "成立":
                continue
            seen.add(key)
            evidence.append(Evidence(kind="verdict", ref=hit["id"],
                                     block_type="verdict", excerpt=hit["text"],
                                     score=hit["score"]))
        # failure_modes 弹药：从生成上下文块里做词面匹配（零额外检索调用；
        # 上下文本身来自 hybrid 检索，failure_modes 已被 block bonus 前置）
        for block in context_blocks:
            if block.block_type != "failure_modes":
                continue
            key = ("block", f"{block.note.article_dir}|{block.text[:40]}")
            if key in seen:
                continue
            seen.add(key)
            evidence.append(Evidence(kind="block", ref=str(block.note.article_dir),
                                     block_type="failure_modes",
                                     excerpt=block.text[:200],
                                     score=block.score))
    return evidence[: EVIDENCE_PER_QUERY * 3 + VERDICT_TOP_K]


def _parse_refine(raw: str) -> RefineOutcome:
    import json as _json
    import re as _re
    text = raw.strip()
    if text.startswith("```"):
        text = _re.sub(r"^```\w*\n?", "", text)
        text = _re.sub(r"\n?```$", "", text)
    try:
        data = _json.loads(text)
        action = str(data.get("action", "defend"))
        if action not in ("revise", "defend", "concede"):
            action = "defend"
        return RefineOutcome(
            action=action,
            revised_core_logic=str(data.get("revised_core_logic", "") or ""),
            revised_what_is_new=str(data.get("revised_what_is_new", "") or ""),
            response=str(data.get("response", "") or ""),
        )
    except Exception:
        return RefineOutcome(action="defend", response="")  # 解析失败=无效回应


def run_deep_brainstorm(
    query: str,
    *,
    kb_root: Path | None = None,
    rounds: int = 3,
    max_ideas: int = 5,
    source_dir: str = "reviewed,high-value",
    retrieval: str = "hybrid",
    top_k: int = 8,
) -> DeepBrainstormResult:
    resolved = resolve_kb_root(kb_root)
    config = LoopConfig(rounds=rounds, max_ideas=max_ideas)
    degraded: list[str] = []

    context_blocks, mode, warning = _load_context_blocks(
        resolved, query, top_k, retrieval, source_dir)
    if warning:
        degraded.append(str(warning))
    falsified = _falsified_directions(resolved)
    if not falsified:
        degraded.append("verdict 层为空——批判仅依赖知识库 failure_modes")

    def generate():
        messages = build_messages("brainstorm", query, format_context(context_blocks))
        if falsified:
            messages[-1]["content"] += (
                "\n\n以下方向近期已被回测证伪或暂不成立，不要原样重提"
                "（可以给出有本质差异的变体并说明差异）：\n"
                + "\n".join(f"- {d}" for d in falsified))
        return parse_ideas(call_llm_chat(messages))

    def criticize(cand: CandidateIdea, round_index: int) -> list[Critique]:
        evidence = _gather_candidate_evidence(cand, resolved, context_blocks)
        return critique_candidate(cand, evidence, call_llm_chat, round_index)

    def refine(cand: CandidateIdea, critiques) -> RefineOutcome:
        crit_lines = []
        for i, c in enumerate(critiques, start=1):
            tag = "" if c.grounded else "（无据推断）"
            crit_lines.append(f"{i}. [{c.severity}]{tag} {c.text}")
        user = (f"想法：{cand.idea.title}\n核心逻辑：{cand.idea.core_logic}\n\n"
                f"红队批判：\n" + "\n".join(crit_lines))
        return _parse_refine(call_llm_chat([
            {"role": "system", "content": REFINE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]))

    def score(alive: list[CandidateIdea]) -> list[tuple[str, str]]:
        ideas = [c.idea for c in alive]
        novelty = check_novelty(ideas, resolved / "vector_store")
        ca = score_coherence_actionability(ideas)
        kills: list[tuple[str, str]] = []
        for i, cand in enumerate(alive):
            t = score_traceability(cand.idea, context_blocks)
            entry = ca[i] if i < len(ca) else {"coherence": 0.5, "actionability": 0.5}
            composite = _compute_composite(t, entry["coherence"], entry["actionability"])
            if not novelty[i].is_novel:
                composite = round(composite - NOVELTY_PENALTY, 2)
            cand.composite = composite
            if composite < config.score_floor:
                kills.append((cand.cid,
                              f"综合分 {composite:.2f} 低于下限 {config.score_floor}"))
        return kills

    log = run_loop(query, generate=generate, criticize=criticize,
                   refine=refine, score=score, config=config)
    log.degraded_notes = degraded + log.degraded_notes

    out_dir = resolved / "outputs" / "brainstorms"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_part = datetime.now().strftime("%Y-%m-%d")
    base = out_dir / f"{date_part}_{slugify(query)}_deep"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")

    md_lines = [f"# Deep Brainstorm: {query}", ""]
    survivors = log.survivors()
    if survivors:
        md_lines.append("## 幸存想法")
        for c in survivors:
            md_lines.append("")
            md_lines.append(c.idea.raw_text or
                            f"### {c.idea.title}\n{c.idea.core_logic}")
    else:
        md_lines.append("## 全灭（证伪机判定：当前方向无幸存想法）")
    md_lines += ["", log.to_markdown(), ""]
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    json_path.write_text(log.to_json(), encoding="utf-8")
    return DeepBrainstormResult(log=log, md_path=md_path, json_path=json_path)
