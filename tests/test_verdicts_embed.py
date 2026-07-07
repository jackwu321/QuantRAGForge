from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.verdicts import (  # noqa: E402
    VerdictRecord,
    embed_all_verdicts,
    embed_verdict,
    retrieve_similar_verdicts,
    save_verdict,
)


def fake_embed(text: str, model=None) -> list[float]:
    """确定性 8 维向量：同文本同向量，不碰任何 API。"""
    digest = hashlib.sha1(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:8]]


@pytest.fixture(autouse=True)
def patch_embed(monkeypatch):
    monkeypatch.setattr("quant_llm_wiki.verdicts.embed_text", fake_embed)


def _record(rid="2026-07-03-low-vol", verdict="被证伪") -> VerdictRecord:
    return VerdictRecord(
        id=rid, date="2026-07-03", direction="沪深300低波动选股",
        hypothesis="低波动股票长期复利占优", verdict=verdict,
        failure_summary="样本内外含成本超额均为负",
    )


class TestEmbedAndRetrieve:
    def test_embed_then_retrieve_roundtrip(self, tmp_path):
        store = tmp_path / "vector_store"
        embed_verdict(_record(), store)
        hits = retrieve_similar_verdicts("低波动 选股 失效", store, top_k=3)
        assert len(hits) == 1
        assert hits[0]["id"] == "2026-07-03-low-vol"
        assert hits[0]["verdict"] == "被证伪"
        assert "低波动" in hits[0]["text"]

    def test_embed_is_idempotent_upsert(self, tmp_path):
        store = tmp_path / "vector_store"
        embed_verdict(_record(), store)
        embed_verdict(_record(), store)
        assert len(retrieve_similar_verdicts("低波动", store, top_k=5)) == 1

    def test_retrieve_missing_store_returns_empty(self, tmp_path):
        assert retrieve_similar_verdicts("任何", tmp_path / "nope") == []

    def test_embed_all_scans_dir(self, tmp_path):
        store = tmp_path / "vector_store"
        save_verdict(tmp_path, _record())
        save_verdict(tmp_path, _record(rid="b", verdict="暂不成立"))
        assert embed_all_verdicts(tmp_path, store) == 2
        assert len(retrieve_similar_verdicts("低波动", store, top_k=5)) == 2
