"""End-to-end memory tests: run_agent with FakeChatOpenAI, real tools, real store."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.robustness.conftest import FakeChatOpenAI  # noqa: E402

from quant_llm_wiki.agent.cli import run_agent  # noqa: E402
from quant_llm_wiki.agent.memory import workflow as wf  # noqa: E402
from quant_llm_wiki.agent.memory.store import MemoryStore  # noqa: E402
from quant_llm_wiki.agent.memory.tools import set_memory_context  # noqa: E402
from quant_llm_wiki.paths import memory_root  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    set_memory_context("main", None)
    return tmp_path


def _run(query, tool_sequence=(), final="Done.", **kwargs):
    fake = FakeChatOpenAI(tool_sequence=list(tool_sequence), final_response=final)
    with patch("quant_llm_wiki.agent.graph.get_llm_config",
               return_value=("k", "https://fake.url/v4", "fake-model")), \
         patch("quant_llm_wiki.agent.graph.ChatOpenAI", return_value=fake):
        rc = run_agent(query=query, **kwargs)
    return rc, fake


class TestMemoryIntegration:
    def test_query_creates_session_and_events(self, tmp_path):
        rc, _ = _run("hello")
        assert rc == 0
        store = MemoryStore(tmp_path)
        row = store.conn.execute("SELECT * FROM sessions").fetchone()
        assert row["status"] == "closed"
        types = [r["event_type"] for r in store.session_events(row["id"])]
        assert types[0] == "session_start" and "prompt" in types and types[-1] == "session_end"
        store.close()

    def test_read_only_query_does_not_write_workflow_md(self, tmp_path):
        _run("健康吗", tool_sequence=[("audit_wiki", {})])
        assert wf.read_sections(tmp_path)["Recent Sessions"] == ""

    def test_memory_tool_call_lands_in_sqlite_and_workflow_md(self, tmp_path):
        rc, _ = _run("记个笔记", tool_sequence=[
            ("record_note", {"text": "低频组合可能更稳", "kind": "hypothesis"})])
        assert rc == 0
        store = MemoryStore(tmp_path)
        notes = store.open_notes("main")
        assert notes and notes[0]["text"] == "低频组合可能更稳"
        store.close()
        assert "record_note" in wf.read_sections(tmp_path)["Recent Sessions"]

    def test_second_session_preamble_carries_tasks_and_handoff(self, tmp_path):
        _run("加任务", tool_sequence=[("add_task", {"text": "测试 fallback 路径"})])
        wf.write_section(tmp_path, "Current Handoff", "先看 429 修复进展")
        _, fake = _run("上次到哪了")
        system_text = str(fake.calls_made[0]["messages"][0].content)
        assert "测试 fallback 路径" in system_text
        assert "先看 429 修复进展" in system_text

    def test_thread_isolation_in_preamble(self, tmp_path):
        _run("加任务", tool_sequence=[("add_task", {"text": "A 线任务"})], thread="A")
        _, fake = _run("hi", thread="B")
        assert "A 线任务" not in str(fake.calls_made[0]["messages"][0].content)

    def test_no_memory_preserves_stateless_behavior(self, tmp_path):
        _run("加任务", tool_sequence=[("add_task", {"text": "seed"})])
        mroot = memory_root(tmp_path)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in mroot.rglob("*") if p.is_file()}
        rc, fake = _run("stateless run", no_memory=True)
        assert rc == 0
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in mroot.rglob("*") if p.is_file()}
        assert before == after
        assert "# 工作记忆（thread:" not in str(fake.calls_made[0]["messages"][0].content)

    def test_memory_does_not_touch_wiki_or_vector_store(self, tmp_path):
        for sub, fname in (("wiki", "INDEX.md"), ("vector_store", "data.bin"),
                           ("raw", "a.md"), ("schema", "s.json")):
            d = tmp_path / sub
            d.mkdir()
            (d / fname).write_text(f"content of {sub}", encoding="utf-8")
        snap = lambda: {  # noqa: E731
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for sub in ("wiki", "vector_store", "raw", "schema")
            for p in (tmp_path / sub).rglob("*") if p.is_file()}
        before = snap()
        _run("记笔记", tool_sequence=[
            ("record_note", {"text": "x", "kind": "observation"}),
            ("add_task", {"text": "y"})])
        assert snap() == before

    def test_summary_flag_invokes_summarizer(self, tmp_path, monkeypatch):
        calls = []
        fake_out = {"session_summary": "总结一句", "new_decisions": [], "new_tasks": [],
                    "updated_handoff": "", "updated_next_steps": []}
        monkeypatch.setattr("quant_llm_wiki.agent.memory.summarizer._llm_summarize",
                            lambda txt: calls.append(txt) or fake_out)
        _run("做点事", want_summary=True)
        assert len(calls) == 1
        assert "总结一句" in wf.read_sections(tmp_path)["Recent Sessions"]
        _run("不开 summary")
        assert len(calls) == 1  # summarizer not invoked without the flag
