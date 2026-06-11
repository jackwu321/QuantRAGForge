from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.agent.memory.tools import set_memory_context  # noqa: E402
from quant_llm_wiki.agent.tools import ALL_TOOLS, save_strategy_brief  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    set_memory_context("main", None)
    return tmp_path


class TestSaveStrategyBrief:
    def test_writes_brief_and_returns_str_path(self, tmp_path):
        out = save_strategy_brief.invoke(
            {"topic": "宏观周期与商品期限结构", "content": "## 方向与约束\n周频，国内品种。"})
        assert isinstance(out, str)
        briefs = list((tmp_path / "outputs" / "brainstorms").glob("*_brief.md"))
        assert len(briefs) == 1
        text = briefs[0].read_text(encoding="utf-8")
        assert "Strategy Brief: 宏观周期与商品期限结构" in text
        assert "Thread: main" in text
        assert "## 方向与约束" in text
        assert str(briefs[0]) in out

    def test_empty_args_return_error_string(self):
        assert save_strategy_brief.invoke({"topic": " ", "content": "x"}).startswith("Error")
        assert save_strategy_brief.invoke({"topic": "x", "content": " "}).startswith("Error")

    def test_registered_in_all_tools(self):
        assert "save_strategy_brief" in [t.name for t in ALL_TOOLS]
