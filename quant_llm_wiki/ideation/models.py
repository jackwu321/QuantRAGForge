"""演化循环的数据结构。全部是纯 dataclass，无 I/O、无 LLM。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from quant_llm_wiki.query.rethink import BrainstormIdea


@dataclass
class Evidence:
    kind: str          # "block" | "verdict"
    ref: str           # 文章路径 或 verdict id
    block_type: str    # failure_modes / wiki_concept / verdict / ...
    excerpt: str
    score: float


@dataclass
class Critique:
    attack_query: str
    text: str
    severity: str      # "fatal" | "major" | "minor"
    grounded: bool     # 是否有检索证据支撑（False = 显式降级标注，D3）
    evidence: list[Evidence] = field(default_factory=list)
    verdict_ids: list[str] = field(default_factory=list)
    round: int = 0


@dataclass
class Revision:
    round: int
    reason: str
    previous_core_logic: str


@dataclass
class CandidateIdea:
    cid: str
    idea: BrainstormIdea
    status: str = "alive"          # "alive" | "killed"
    born_round: int = 0
    revisions: list[Revision] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)
    kill_reason: str = ""
    kill_round: int | None = None
    composite: float | None = None


@dataclass
class RoundRecord:
    index: int
    events: list[str] = field(default_factory=list)
    modified: bool = False


@dataclass
class EvolutionLog:
    query: str
    started: str
    config: dict
    candidates: list[CandidateIdea] = field(default_factory=list)
    rounds: list[RoundRecord] = field(default_factory=list)
    stopped_reason: str = ""
    degraded_notes: list[str] = field(default_factory=list)

    def survivors(self) -> list[CandidateIdea]:
        return [c for c in self.candidates if c.status == "alive"]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        lines = ["## 演化日志", "", f"- Query: {self.query}",
                 f"- 开始: {self.started}", f"- 终止原因: {self.stopped_reason}"]
        for note in self.degraded_notes:
            lines.append(f"- ⚠️ 降级: {note}")
        for rr in self.rounds:
            lines.append("")
            lines.append(f"### 第 {rr.index} 轮" + ("（有修订）" if rr.modified else ""))
            lines.extend(f"- {e}" for e in rr.events)
        lines.append("")
        lines.append("### 候选最终状态")
        for c in self.candidates:
            if c.status == "alive":
                score = f"{c.composite:.2f}" if c.composite is not None else "-"
                lines.append(f"- {c.cid} 存活（{c.idea.title}，综合分 {score}，"
                             f"修订 {len(c.revisions)} 次）")
            else:
                lines.append(f"- {c.cid} 淘汰于第 {c.kill_round} 轮"
                             f"（{c.idea.title}）：{c.kill_reason}")
        return "\n".join(lines)
