from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.ideation.models import (  # noqa: E402
    CandidateIdea, Critique, Evidence, EvolutionLog, RoundRecord,
)
from quant_llm_wiki.query.rethink import BrainstormIdea  # noqa: E402


def _idea(title="低波+趋势过滤") -> BrainstormIdea:
    return BrainstormIdea(
        title=title, inspired_by="A文章", core_logic="低波选股叠加趋势过滤",
        what_is_new="双因子串联", why_it_might_work="防御+择时",
        what_could_break="牛市踏空", possible_variants="换用ETF", raw_text="…")


def _log() -> EvolutionLog:
    alive = CandidateIdea(cid="c1", idea=_idea())
    dead = CandidateIdea(cid="c2", idea=_idea("纯低波"), status="killed",
                         kill_reason="相似方向已被回测证伪", kill_round=1)
    dead.critiques.append(Critique(
        attack_query="纯低波 失效", text="2026-07-03 回测证伪 [V1]",
        severity="fatal", grounded=True,
        evidence=[Evidence(kind="verdict", ref="2026-07-03-low-vol",
                           block_type="verdict", excerpt="样本内外均负", score=0.9)],
        verdict_ids=["2026-07-03-low-vol"], round=1))
    return EvolutionLog(
        query="低波方向", started="2026-07-06T10:00:00", config={"rounds": 3},
        candidates=[alive, dead],
        rounds=[RoundRecord(index=1, events=["c2: killed"], modified=False)],
        stopped_reason="收敛稳定", degraded_notes=[])


def test_survivors_filters_alive():
    assert [c.cid for c in _log().survivors()] == ["c1"]


def test_to_json_roundtrips_and_keeps_chinese():
    data = json.loads(_log().to_json())
    assert data["query"] == "低波方向"
    assert data["candidates"][1]["kill_reason"] == "相似方向已被回测证伪"
    assert data["candidates"][1]["critiques"][0]["verdict_ids"] == ["2026-07-03-low-vol"]
    assert "低波方向" in _log().to_json()  # ensure_ascii=False


def test_to_markdown_has_rounds_and_kills():
    md = _log().to_markdown()
    assert "## 演化日志" in md
    assert "第 1 轮" in md
    assert "c2" in md and "相似方向已被回测证伪" in md
    assert "收敛稳定" in md
