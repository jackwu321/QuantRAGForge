from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.agent.memory.tools import set_memory_context  # noqa: E402
from quant_llm_wiki.agent.tools import save_strategy_brief  # noqa: E402
from quant_llm_wiki.handoff import (  # noqa: E402
    HandoffError, load_handoff_schema, render_handoff_yaml,
)

SCHEMA = {
    "type": "object",
    "required": ["hypothesis", "compile"],
    "properties": {
        "hypothesis": {"type": "string"},
        "compile": {"type": "object", "required": ["factor_expr"],
                    "properties": {"factor_expr": {"type": "string"}}},
    },
}
GOOD_YAML = "hypothesis: 低波占优\ncompile:\n  factor_expr: \"0-Std($close,20)\"\n"


@pytest.fixture(autouse=True)
def isolated_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    set_memory_context("main", None)
    return tmp_path


def _install_schema(kb: Path) -> None:
    d = kb / ".qlw"
    d.mkdir(parents=True, exist_ok=True)
    (d / "handoff_schema.json").write_text(
        json.dumps(SCHEMA, ensure_ascii=False), encoding="utf-8")


class TestSchemaLoading:
    def test_absent_returns_none(self, tmp_path):
        assert load_handoff_schema(tmp_path) is None

    def test_bad_json_raises(self, tmp_path):
        (tmp_path / ".qlw").mkdir()
        (tmp_path / ".qlw" / "handoff_schema.json").write_text("{oops", encoding="utf-8")
        with pytest.raises(HandoffError):
            load_handoff_schema(tmp_path)


class TestRender:
    def test_first_shot_valid(self):
        out = render_handoff_yaml("t", "内容", SCHEMA, lambda m: GOOD_YAML)
        assert yaml.safe_load(out)["hypothesis"] == "低波占优"

    def test_repair_loop_feeds_error_back(self):
        calls = []
        def llm(messages):
            calls.append(messages[-1]["content"])
            return "hypothesis: 只有假设\n" if len(calls) == 1 else GOOD_YAML
        out = render_handoff_yaml("t", "内容", SCHEMA, llm)
        assert yaml.safe_load(out)["compile"]["factor_expr"]
        assert len(calls) == 2 and "compile" in calls[1]  # 校验错误已反馈

    def test_three_failures_raise(self):
        with pytest.raises(HandoffError):
            render_handoff_yaml("t", "内容", SCHEMA, lambda m: "hypothesis: 差字段\n")


class TestSaveBriefIntegration:
    def test_no_schema_md_only(self, tmp_path):
        out = save_strategy_brief.invoke({"topic": "方向", "content": "正文"})
        assert "handoff" not in out
        assert list((tmp_path / "outputs" / "brainstorms").glob("*.yaml")) == []

    def test_with_schema_writes_yaml_sibling(self, tmp_path):
        _install_schema(tmp_path)
        with patch("quant_llm_wiki.handoff.call_llm_chat", return_value=GOOD_YAML):
            out = save_strategy_brief.invoke({"topic": "方向", "content": "正文"})
        yamls = list((tmp_path / "outputs" / "brainstorms").glob("*_brief.yaml"))
        assert len(yamls) == 1 and str(yamls[0]) in out

    def test_render_failure_keeps_md_and_warns(self, tmp_path):
        _install_schema(tmp_path)
        with patch("quant_llm_wiki.handoff.call_llm_chat",
                   return_value="hypothesis: 缺 compile\n"):
            out = save_strategy_brief.invoke({"topic": "方向", "content": "正文"})
        assert "warning" in out and "md 为兜底" in out
        assert len(list((tmp_path / "outputs" / "brainstorms").glob("*_brief.md"))) == 1
        assert list((tmp_path / "outputs" / "brainstorms").glob("*.yaml")) == []
