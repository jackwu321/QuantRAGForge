from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.ideation.loop import LoopConfig, RefineOutcome, run_loop  # noqa: E402
from quant_llm_wiki.ideation.models import Critique, Evidence  # noqa: E402
from quant_llm_wiki.query.rethink import BrainstormIdea  # noqa: E402


def _idea(title: str) -> BrainstormIdea:
    return BrainstormIdea(title=title, inspired_by="src", core_logic=f"{title} 逻辑",
                          what_is_new="新", why_it_might_work="有理",
                          what_could_break="风险", possible_variants="", raw_text="")


def _fatal(round_=1) -> Critique:
    return Critique(attack_query="q", text="同类已证伪 [V1]", severity="fatal",
                    grounded=True, round=round_,
                    evidence=[Evidence("verdict", "v-1", "verdict", "均负", 0.9)],
                    verdict_ids=["v-1"])


NO_KILL = lambda cands: []          # noqa: E731
NO_CRIT = lambda cand, r: []        # noqa: E731
NO_REFINE = lambda cand, crits: RefineOutcome(action="defend", response="[E1] 已答")  # noqa: E731


def test_trajectory_revise_survives():
    """轨迹 1：批判→修订→下一轮无批判→收敛稳定，幸存带 lineage。"""
    calls = {"n": 0}
    def criticize(cand, r):
        calls["n"] += 1
        return [_fatal(r)] if r == 1 else []
    def refine(cand, crits):
        return RefineOutcome(action="revise", revised_core_logic="改良逻辑",
                             response="吸收批判")
    log = run_loop("q", generate=lambda: [_idea("A")], criticize=criticize,
                   refine=refine, score=NO_KILL, config=LoopConfig(rounds=3))
    assert log.stopped_reason == "收敛稳定（本轮无修订）"
    survivors = log.survivors()
    assert len(survivors) == 1
    assert survivors[0].idea.core_logic == "改良逻辑"
    assert len(survivors[0].revisions) == 1
    assert survivors[0].revisions[0].previous_core_logic == "A 逻辑"


def test_trajectory_fatal_grounded_unanswered_killed():
    """轨迹 2：fatal+grounded 批判，defend 不引用证据 → 淘汰。"""
    def refine(cand, crits):
        return RefineOutcome(action="defend", response="我觉得没问题")  # 无 [E/[V 引用
    log = run_loop("q", generate=lambda: [_idea("A")],
                   criticize=lambda c, r: [_fatal(r)],
                   refine=refine, score=NO_KILL, config=LoopConfig(rounds=3))
    assert log.stopped_reason == "全灭"
    dead = log.candidates[0]
    assert dead.status == "killed" and dead.kill_round == 1
    assert "fatal" in dead.kill_reason


def test_trajectory_all_killed_reports_reasons():
    """轨迹 3：concede 全灭，死因逐个保留。"""
    def refine(cand, crits):
        return RefineOutcome(action="concede")
    log = run_loop("q", generate=lambda: [_idea("A"), _idea("B")],
                   criticize=lambda c, r: [_fatal(r)],
                   refine=refine, score=NO_KILL, config=LoopConfig(rounds=3))
    assert log.stopped_reason == "全灭"
    assert all(c.status == "killed" and c.kill_reason for c in log.candidates)
    assert log.survivors() == []


def test_trajectory_round_cap():
    """轨迹 4：每轮都修订 → 跑满上限。"""
    def refine(cand, crits):
        return RefineOutcome(action="revise", revised_core_logic=cand.idea.core_logic + "+",
                             response="改")
    log = run_loop("q", generate=lambda: [_idea("A")],
                   criticize=lambda c, r: [_fatal(r)],
                   refine=refine, score=NO_KILL, config=LoopConfig(rounds=2))
    assert log.stopped_reason == "达到轮数上限"
    assert len(log.rounds) == 2


def test_score_kill_applied_and_max_ideas_capped():
    def score(cands):
        for c in cands:
            c.composite = 0.9 if c.cid == "c1" else 0.2
        return [(c.cid, "综合分过低") for c in cands if c.cid != "c1"]
    log = run_loop("q", generate=lambda: [_idea(t) for t in "ABCDEFG"],
                   criticize=NO_CRIT, refine=NO_REFINE, score=score,
                   config=LoopConfig(rounds=1, max_ideas=3))
    assert len(log.candidates) == 3            # 截断到 max_ideas
    assert [c.cid for c in log.survivors()] == ["c1"]
    assert log.candidates[1].kill_reason == "综合分过低"


def test_empty_generation():
    log = run_loop("q", generate=lambda: [], criticize=NO_CRIT,
                   refine=NO_REFINE, score=NO_KILL, config=LoopConfig())
    assert log.stopped_reason == "生成为空"
    assert log.candidates == [] and log.rounds == []
