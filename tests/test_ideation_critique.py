from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.ideation.critique import (  # noqa: E402
    build_attack_queries, critique_candidate,
)
from quant_llm_wiki.ideation.models import CandidateIdea, Evidence  # noqa: E402
from quant_llm_wiki.query.rethink import BrainstormIdea  # noqa: E402


def _cand() -> CandidateIdea:
    return CandidateIdea(cid="c1", idea=BrainstormIdea(
        title="低波+趋势过滤", inspired_by="A", core_logic="低波选股叠加趋势过滤",
        what_is_new="双因子串联", why_it_might_work="防御",
        what_could_break="牛市踏空", possible_variants="", raw_text=""))


def test_attack_queries_are_three_deterministic_angles():
    qs = build_attack_queries(_cand().idea)
    assert len(qs) == 3
    assert qs == build_attack_queries(_cand().idea)      # 确定性
    joined = " ".join(qs)
    assert "失效" in joined and "拥挤" in joined and "市场状态" in joined
    assert "牛市踏空" in joined                            # 复用 what_could_break


EV = [Evidence(kind="verdict", ref="2026-07-03-low-vol", block_type="verdict",
               excerpt="低波方向样本内外均负", score=0.9),
      Evidence(kind="block", ref="articles/a", block_type="failure_modes",
               excerpt="低波在牛市大幅跑输", score=0.7)]


def test_grounded_critique_cites_evidence():
    def llm(messages):
        return json.dumps([{"attack_query": "q", "text": "同类已证伪 [E1]",
                            "severity": "fatal", "evidence_indexes": [1]}])
    crits = critique_candidate(_cand(), EV, llm, round_index=1)
    assert len(crits) == 1
    assert crits[0].grounded is True
    assert crits[0].severity == "fatal"
    assert crits[0].evidence[0].ref == "2026-07-03-low-vol"
    assert crits[0].verdict_ids == ["2026-07-03-low-vol"]
    assert crits[0].round == 1


def test_bad_evidence_index_degrades_to_ungrounded():
    def llm(messages):
        return json.dumps([{"attack_query": "q", "text": "凭空推断",
                            "severity": "major", "evidence_indexes": [99]}])
    crits = critique_candidate(_cand(), EV, llm, round_index=1)
    assert crits[0].grounded is False and crits[0].evidence == []


def test_no_evidence_yields_single_ungrounded_critique():
    def llm(messages):
        assert "知识库无反例" in messages[-1]["content"]
        return json.dumps([{"attack_query": "q", "text": "逻辑上可能过拟合",
                            "severity": "minor", "evidence_indexes": []}])
    crits = critique_candidate(_cand(), [], llm, round_index=2)
    assert len(crits) == 1 and crits[0].grounded is False


def test_unparseable_llm_output_returns_empty():
    assert critique_candidate(_cand(), EV, lambda m: "not json", round_index=1) == []


def test_invalid_severity_clamped_to_minor():
    def llm(messages):
        return json.dumps([{"attack_query": "q", "text": "x",
                            "severity": "catastrophic", "evidence_indexes": [1]}])
    assert critique_candidate(_cand(), EV, llm, round_index=1)[0].severity == "minor"
