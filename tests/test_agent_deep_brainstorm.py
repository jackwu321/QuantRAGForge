from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.agent.tools import ALL_TOOLS, deep_brainstorm  # noqa: E402


def test_registered_in_all_tools():
    assert "deep_brainstorm" in [t.name for t in ALL_TOOLS]


def test_invokes_engine_and_returns_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    fake = MagicMock()
    fake.summary_text.return_value = "深化脑暴完成：X\n幸存想法 1 个"
    with patch("quant_llm_wiki.ideation.deep.run_deep_brainstorm",
               return_value=fake) as mock_run:
        out = deep_brainstorm.invoke({"query": "低波方向", "rounds": 2, "max_ideas": 4})
    assert "幸存想法" in out
    kwargs = mock_run.call_args.kwargs
    assert kwargs["rounds"] == 2 and kwargs["max_ideas"] == 4


def test_engine_error_returns_human_string(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    with patch("quant_llm_wiki.ideation.deep.run_deep_brainstorm",
               side_effect=RuntimeError("LLM down")):
        out = deep_brainstorm.invoke({"query": "x"})
    assert out.startswith("Error") and "LLM down" in out


def test_sop_v3_references_deep_brainstorm():
    sop = (ROOT / "quant_llm_wiki" / "agent" / "skills" /
           "strategy-brainstorm.md").read_text(encoding="utf-8")
    assert "version: 3" in sop
    assert "deep_brainstorm" in sop
    assert "[PAUSE]" in sop            # PAUSE 结构不动
    assert "handoff" in sop            # 阶段 5 提及双产物
