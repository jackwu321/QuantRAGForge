"""轮次引擎：生成→批判→精炼/淘汰→打分筛选，全依赖注入（设计 D2）。

引擎本身无 LLM、无检索、无 I/O——四个 callable 全部由装配层（deep.py）
或测试提供，循环行为可用纯函数测试穷举。淘汰规则由代码强制，不靠提示词。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from quant_llm_wiki.ideation.models import (
    CandidateIdea, Critique, EvolutionLog, Revision, RoundRecord,
)
from quant_llm_wiki.query.rethink import BrainstormIdea


@dataclass
class LoopConfig:
    rounds: int = 3
    max_ideas: int = 5
    score_floor: float = 0.40


@dataclass
class RefineOutcome:
    action: str                    # "revise" | "defend" | "concede"
    revised_core_logic: str = ""
    revised_what_is_new: str = ""
    response: str = ""


def _has_evidence_ref(text: str) -> bool:
    return "[E" in text or "[V" in text


def _strongest(critiques: list[Critique]) -> Critique:
    order = {"fatal": 0, "major": 1, "minor": 2}
    return sorted(critiques, key=lambda c: order.get(c.severity, 3))[0]


def run_loop(
    query: str,
    *,
    generate: Callable[[], list[BrainstormIdea]],
    criticize: Callable[[CandidateIdea, int], list[Critique]],
    refine: Callable[[CandidateIdea, list[Critique]], RefineOutcome],
    score: Callable[[list[CandidateIdea]], list[tuple[str, str]]],
    config: LoopConfig,
    started: str | None = None,
) -> EvolutionLog:
    log = EvolutionLog(
        query=query,
        started=started or datetime.now().isoformat(timespec="seconds"),
        config={"rounds": config.rounds, "max_ideas": config.max_ideas,
                "score_floor": config.score_floor},
    )
    ideas = list(generate())[: config.max_ideas]
    if not ideas:
        log.stopped_reason = "生成为空"
        return log
    log.candidates = [
        CandidateIdea(cid=f"c{i}", idea=idea) for i, idea in enumerate(ideas, start=1)
    ]

    def _kill(cand: CandidateIdea, reason: str, round_index: int, rr: RoundRecord) -> None:
        cand.status = "killed"
        cand.kill_reason = reason
        cand.kill_round = round_index
        rr.events.append(f"{cand.cid}: killed —— {reason}")

    for round_index in range(1, config.rounds + 1):
        rr = RoundRecord(index=round_index)
        alive = [c for c in log.candidates if c.status == "alive"]
        for cand in alive:
            critiques = criticize(cand, round_index)
            cand.critiques.extend(critiques)
            if not critiques:
                rr.events.append(f"{cand.cid}: 本轮无批判")
                continue
            n_ungrounded = sum(1 for c in critiques if not c.grounded)
            rr.events.append(
                f"{cand.cid}: 收到 {len(critiques)} 条批判"
                + (f"（其中 {n_ungrounded} 条无据推断）" if n_ungrounded else "")
            )
            outcome = refine(cand, critiques)
            fatal_grounded = [c for c in critiques
                              if c.severity == "fatal" and c.grounded]
            if outcome.action == "concede":
                _kill(cand, f"认输：{_strongest(critiques).text}", round_index, rr)
            elif outcome.action == "revise":
                cand.revisions.append(Revision(
                    round=round_index,
                    reason=outcome.response or _strongest(critiques).text,
                    previous_core_logic=cand.idea.core_logic,
                ))
                if outcome.revised_core_logic:
                    cand.idea.core_logic = outcome.revised_core_logic
                if outcome.revised_what_is_new:
                    cand.idea.what_is_new = outcome.revised_what_is_new
                rr.modified = True
                rr.events.append(f"{cand.cid}: 修订核心逻辑")
            else:  # defend
                if fatal_grounded and not _has_evidence_ref(outcome.response):
                    _kill(cand, "fatal 有据批判未获有效回应（反驳未引用证据）",
                          round_index, rr)
                else:
                    rr.events.append(f"{cand.cid}: 有据反驳，维持原案")

        still_alive = [c for c in log.candidates if c.status == "alive"]
        if still_alive:
            for cid, reason in score(still_alive):
                cand = next(c for c in still_alive if c.cid == cid)
                _kill(cand, reason, round_index, rr)

        log.rounds.append(rr)
        if not any(c.status == "alive" for c in log.candidates):
            log.stopped_reason = "全灭"
            return log
        if not rr.modified:
            log.stopped_reason = "收敛稳定（本轮无修订）"
            return log

    log.stopped_reason = "达到轮数上限"
    return log
