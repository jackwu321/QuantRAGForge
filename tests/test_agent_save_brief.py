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

    @pytest.mark.parametrize("evil_topic, expected_slug_part", [
        ("../../etc/passwd", "etc_passwd"),
        ("...", "result"),
    ])
    def test_topic_cannot_escape_output_dir(self, tmp_path, evil_topic, expected_slug_part):
        out = save_strategy_brief.invoke({"topic": evil_topic, "content": "body"})
        briefs = list((tmp_path / "outputs" / "brainstorms").glob("*_brief.md"))
        assert len(briefs) == 1
        resolved = briefs[0].resolve()
        assert resolved.parent == (tmp_path / "outputs" / "brainstorms").resolve()
        assert expected_slug_part in resolved.name
        assert str(briefs[0]) in out

    def test_query_log_written_and_wiki_state_untouched(self, tmp_path):
        save_strategy_brief.invoke({"topic": "动量方向", "content": "## 简报\n无来源章节。"})
        logs = list((tmp_path / "wiki" / "queries").glob("*_brief.md"))
        assert len(logs) == 1
        state_path = tmp_path / "wiki" / "state.json"
        if state_path.exists():
            import json
            state = json.loads(state_path.read_text(encoding="utf-8"))
            assert state.get("concepts", {}) == {}

    def test_same_day_same_topic_does_not_clobber_earlier_brief(self, tmp_path):
        save_strategy_brief.invoke({"topic": "动量方向", "content": "第一版结论"})
        save_strategy_brief.invoke({"topic": "动量方向", "content": "第二版结论"})
        briefs = sorted((tmp_path / "outputs" / "brainstorms").glob("*_brief*.md"))
        assert len(briefs) == 2
        texts = [b.read_text(encoding="utf-8") for b in briefs]
        assert any("第一版结论" in t for t in texts)
        assert any("第二版结论" in t for t in texts)
        logs = list((tmp_path / "wiki" / "queries").glob("*_brief*.md"))
        assert len(logs) == 2

    def test_control_chars_in_topic_are_sanitized_not_crashing(self, tmp_path):
        out = save_strategy_brief.invoke({"topic": "动量\x00方向\n## 假标题", "content": "body"})
        assert isinstance(out, str) and not out.startswith("Error")
        briefs = list((tmp_path / "outputs" / "brainstorms").glob("*_brief.md"))
        assert len(briefs) == 1
        first_line = briefs[0].read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("# Strategy Brief: ")
        assert "\x00" not in briefs[0].name
        assert "## 假标题" not in first_line or "\n" not in first_line

    def test_brief_with_retrieved_sources_never_bumps_wiki_state(self, tmp_path):
        # Brief content is conversation-authored: even a well-formed Retrieved
        # Sources section citing a real concept must not mutate state.json.
        concept = tmp_path / "wiki" / "concepts" / "momentum-strategies.md"
        concept.parent.mkdir(parents=True)
        concept.write_text("# Momentum\n", encoding="utf-8")
        content = (
            "## 简报\n\n方向已收敛。\n\n"
            "## Retrieved Sources\n\n"
            f"- {concept}\n\n"
            "## 下一步建议\n\n回测。\n"
        )
        save_strategy_brief.invoke({"topic": "动量收敛", "content": content})
        logs = list((tmp_path / "wiki" / "queries").glob("*_brief.md"))
        assert len(logs) == 1
        assert not (tmp_path / "wiki" / "state.json").exists()
