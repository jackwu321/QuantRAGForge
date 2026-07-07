from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki import verdicts as verdicts_mod  # noqa: E402


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "v.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


VALID = {
    "id": "2026-07-03-low-vol", "date": "2026-07-03",
    "direction": "沪深300低波动选股", "hypothesis": "低波动占优",
    "verdict": "被证伪", "failure_summary": "样本内外均负",
}


class TestVerdictAdd:
    def test_add_saves_and_embeds(self, tmp_path, capsys):
        src = _write_yaml(tmp_path, VALID)
        with patch("quant_llm_wiki.verdicts.embed_verdict") as mock_embed:
            rc = verdicts_mod.run_add(src, kb_root=tmp_path)
        assert rc == 0
        assert (tmp_path / "verdicts" / "2026-07-03-low-vol.yaml").exists()
        mock_embed.assert_called_once()
        assert "saved" in capsys.readouterr().out

    def test_add_invalid_returns_2_with_human_error(self, tmp_path, capsys):
        src = _write_yaml(tmp_path, {**VALID, "verdict": "也许"})
        rc = verdicts_mod.run_add(src, kb_root=tmp_path)
        assert rc == 2
        assert "verdict 必须是" in capsys.readouterr().out
        assert not (tmp_path / "verdicts").exists()

    def test_add_embed_failure_warns_but_succeeds(self, tmp_path, capsys):
        src = _write_yaml(tmp_path, VALID)
        with patch("quant_llm_wiki.verdicts.embed_verdict",
                   side_effect=RuntimeError("chroma down")):
            rc = verdicts_mod.run_add(src, kb_root=tmp_path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "warning" in out and "embed_knowledge" in out
        assert (tmp_path / "verdicts" / "2026-07-03-low-vol.yaml").exists()


class TestVerdictList:
    def test_list_prints_records(self, tmp_path, capsys):
        verdicts_mod.save_verdict(tmp_path, verdicts_mod.parse_verdict_data(VALID))
        rc = verdicts_mod.run_list(kb_root=tmp_path, verdict=None)
        assert rc == 0
        out = capsys.readouterr().out
        assert "2026-07-03-low-vol" in out and "被证伪" in out

    def test_list_empty(self, tmp_path, capsys):
        rc = verdicts_mod.run_list(kb_root=tmp_path, verdict=None)
        assert rc == 0
        assert "no verdicts" in capsys.readouterr().out
