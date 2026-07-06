from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.verdicts import (  # noqa: E402
    VALID_VERDICTS,
    VerdictError,
    VerdictRecord,
    list_verdicts,
    load_verdict,
    parse_verdict_data,
    save_verdict,
    verdict_embed_text,
    verdicts_dir,
)


def _record(**overrides) -> VerdictRecord:
    base = dict(
        id="2026-07-03-low-vol-daily",
        date="2026-07-03",
        direction="沪深300低波动选股",
        hypothesis="低波动的股票长期复利占优",
        verdict="被证伪",
        metrics={"in_sample_ann_excess_with_cost": -0.005,
                 "out_sample_ann_excess_with_cost": -0.12},
        failure_summary="样本内外含成本超额均为负，牛市踏空",
        universe="csi300",
        period="2012-01-01~2020-09-24",
        source_brief="outputs/brainstorms/x_brief.md",
    )
    base.update(overrides)
    return VerdictRecord(**base)


class TestStoreRoundtrip:
    def test_save_load_roundtrip(self, tmp_path):
        path = save_verdict(tmp_path, _record())
        assert path == verdicts_dir(tmp_path) / "2026-07-03-low-vol-daily.yaml"
        loaded = load_verdict(path)
        assert loaded == _record()

    def test_same_id_is_idempotent_update(self, tmp_path):
        save_verdict(tmp_path, _record())
        save_verdict(tmp_path, _record(verdict="暂不成立"))
        records = list_verdicts(tmp_path)
        assert len(records) == 1
        assert records[0].verdict == "暂不成立"

    def test_list_filters_and_sorts_desc(self, tmp_path):
        save_verdict(tmp_path, _record())
        save_verdict(tmp_path, _record(id="b", date="2026-07-05", verdict="成立"))
        assert [r.id for r in list_verdicts(tmp_path)] == ["b", "2026-07-03-low-vol-daily"]
        assert [r.id for r in list_verdicts(tmp_path, verdict="被证伪")] == ["2026-07-03-low-vol-daily"]

    def test_list_empty_dir(self, tmp_path):
        assert list_verdicts(tmp_path) == []


class TestValidation:
    def test_missing_required_field_raises(self):
        with pytest.raises(VerdictError, match="direction"):
            parse_verdict_data({"id": "x", "date": "2026-01-01",
                                "hypothesis": "h", "verdict": "成立"})

    def test_invalid_verdict_value_raises(self):
        with pytest.raises(VerdictError, match="verdict"):
            parse_verdict_data({"id": "x", "date": "2026-01-01", "direction": "d",
                                "hypothesis": "h", "verdict": "也许吧"})

    def test_extra_fields_preserved(self, tmp_path):
        data = {"id": "x", "date": "2026-01-01", "direction": "d",
                "hypothesis": "h", "verdict": "成立", "engine": "qlib-template-v1"}
        rec = parse_verdict_data(data)
        assert rec.extra == {"engine": "qlib-template-v1"}
        path = save_verdict(tmp_path, rec)
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["engine"] == "qlib-template-v1"


def test_embed_text_composition():
    text = verdict_embed_text(_record())
    assert "沪深300低波动选股" in text
    assert "低波动的股票长期复利占优" in text
    assert "牛市踏空" in text
    assert "被证伪" in text


def test_all_four_verdict_levels_accepted():
    assert set(VALID_VERDICTS) == {"成立", "暂不成立", "被证伪", "需要更多数据"}
