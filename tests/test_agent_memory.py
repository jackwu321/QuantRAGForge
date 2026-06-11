from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.agent.memory import workflow as wf  # noqa: E402
from quant_llm_wiki.agent.memory.hooks import MemorySession  # noqa: E402
from quant_llm_wiki.agent.memory.recall import compose_preamble, recall  # noqa: E402
from quant_llm_wiki.agent.memory.store import MemoryStore  # noqa: E402
from quant_llm_wiki.agent.memory.tools import (  # noqa: E402
    MEMORY_TOOLS,
    add_task,
    complete_task,
    list_open_tasks,
    propose_procedure,
    record_decision,
    record_note,
    set_note_status,
    set_memory_context,
)
from quant_llm_wiki.paths import memory_root  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    set_memory_context("main", None)
    return tmp_path


# ---------------------------------------------------------------------------
# store.py
# ---------------------------------------------------------------------------


class TestStore:
    def test_memory_root_created_idempotent(self, tmp_path):
        s1 = MemoryStore(tmp_path)
        s1.close()
        s2 = MemoryStore(tmp_path)
        s2.close()
        assert memory_root(tmp_path).is_dir()
        assert (memory_root(tmp_path) / "memory.sqlite").exists()

    def test_schema_init_idempotent(self, tmp_path):
        for _ in range(2):
            store = MemoryStore(tmp_path)
            store.close()
        store = MemoryStore(tmp_path)
        tables = {r[0] for r in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sessions", "tasks", "decisions", "procedures", "events",
                "threads", "notes"} <= tables
        store.close()

    def test_task_roundtrip(self, tmp_path):
        store = MemoryStore(tmp_path)
        tid = store.add_task("test fallback path", "main")
        assert [r["id"] for r in store.open_tasks("main")] == [tid]
        assert store.complete_task(tid, "done in tests")
        assert store.open_tasks("main") == []
        assert not store.complete_task(tid)  # already done
        store.close()

    def test_decision_insert_and_recall(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.record_decision("use FTS5 with LIKE fallback", "main", "portability")
        rows = store.recent_decisions("main")
        assert rows[0]["text"] == "use FTS5 with LIKE fallback"
        hits = recall(store, "fallback")
        assert any(h["type"] == "decision" for h in hits)
        store.close()

    def test_procedure_draft_pool(self, tmp_path):
        store = MemoryStore(tmp_path)
        pid = store.propose_procedure("zhipu-429-drill", "rate limit", ["check Retry-After", "backoff"])
        assert store.get_procedure(pid)["status"] == "draft"
        assert [r["id"] for r in store.draft_procedures()] == [pid]
        assert store.set_procedure_status(pid, "promoted")
        assert store.draft_procedures() == []
        store.close()

    def test_notes_lifecycle(self, tmp_path):
        store = MemoryStore(tmp_path)
        nid = store.record_note("低频多策略可能比单策略稳", "main", kind="hypothesis")
        assert [r["id"] for r in store.open_notes("main")] == [nid]
        assert store.set_note_status(nid, "folded")
        assert store.open_notes("main") == []
        nid2 = store.record_note("动量+宏观组合方向", "main", kind="direction")
        assert store.set_note_status(nid2, "rejected")
        assert store.open_notes("main") == []
        assert store.all_notes("main")[0]["status"] == "rejected"
        with pytest.raises(ValueError):
            store.record_note("x", "main", kind="banana")
        with pytest.raises(ValueError):
            store.set_note_status(nid, "banana")
        store.close()

    def test_thread_isolation(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.add_task("only in A", "A")
        assert store.open_tasks("B") == []
        store.record_note("A note", "A")
        assert store.open_notes("B") == []
        store.close()

    def test_like_fallback_when_fts_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("quant_llm_wiki.agent.memory.store._fts5_available",
                            lambda conn: False)
        store = MemoryStore(tmp_path)
        assert store.fts_enabled is False
        store.add_task("verify degraded recall", "main")
        store.record_note("an observation about momentum", "main")
        hits = recall(store, "degraded")
        assert any(h["type"] == "task" for h in hits)
        hits = recall(store, "momentum")
        assert any(h["type"] == "note" for h in hits)
        store.close()


# ---------------------------------------------------------------------------
# workflow.py
# ---------------------------------------------------------------------------


class TestWorkflowMd:
    def test_skeleton_and_section_io(self, tmp_path):
        wf.ensure_workflow(tmp_path)
        assert wf.read_sections(tmp_path) == {s: "" for s in wf.SECTIONS}
        wf.write_section(tmp_path, "Current Handoff", "下一步先跑 lint")
        wf.write_section(tmp_path, "Blockers", "- 等 API 配额")
        sections = wf.read_sections(tmp_path)
        assert sections["Current Handoff"] == "下一步先跑 lint"
        assert sections["Blockers"] == "- 等 API 配额"
        assert sections["Next Steps"] == ""

    def test_write_section_preserves_other_sections(self, tmp_path):
        wf.ensure_workflow(tmp_path)
        wf.write_section(tmp_path, "Next Steps", "- step one")
        wf.write_section(tmp_path, "Current Handoff", "handoff text")
        assert wf.read_sections(tmp_path)["Next Steps"] == "- step one"

    def test_recent_sessions_cap(self, tmp_path):
        wf.ensure_workflow(tmp_path)
        for i in range(13):
            wf.prepend_recent_session(tmp_path, wf.session_entry("main", f"session {i}"), keep=10)
        body = wf.read_sections(tmp_path)["Recent Sessions"]
        entries = [e for e in body.split("### ") if e.strip()]
        assert len(entries) == 10
        assert "session 12" in entries[0]
        assert "session 0" not in body

    def test_merge_next_steps_dedup(self, tmp_path):
        wf.ensure_workflow(tmp_path)
        wf.merge_next_steps(tmp_path, ["run lint", "check cache"])
        wf.merge_next_steps(tmp_path, ["run lint", "ship it"])
        body = wf.read_sections(tmp_path)["Next Steps"]
        assert body.count("run lint") == 1
        assert "ship it" in body

    def test_section_sha_detects_human_edit(self, tmp_path):
        wf.ensure_workflow(tmp_path)
        wf.write_section(tmp_path, "Current Handoff", "original")
        before = wf.section_sha(tmp_path, "Current Handoff")
        path = wf.workflow_path(tmp_path)
        path.write_text(path.read_text(encoding="utf-8").replace("original", "hand edited"),
                        encoding="utf-8")
        assert wf.section_sha(tmp_path, "Current Handoff") != before


# ---------------------------------------------------------------------------
# tools.py
# ---------------------------------------------------------------------------


class TestMemoryTools:
    def test_seven_tools_registered(self):
        assert [t.name for t in MEMORY_TOOLS] == [
            "record_decision", "add_task", "complete_task",
            "list_open_tasks", "propose_procedure", "record_note",
            "set_note_status"]

    def test_tools_return_strings_and_write_sqlite(self, tmp_path):
        out = record_decision.invoke({"text": "决定 A", "rationale": "因为 B"})
        assert isinstance(out, str) and "recorded" in out
        out = add_task.invoke({"text": "任务 1"})
        assert "Task #" in out
        out = list_open_tasks.invoke({})
        assert "任务 1" in out
        out = complete_task.invoke({"task_id": 1, "note": "ok"})
        assert "done" in out
        out = propose_procedure.invoke({"name": "drill", "steps": ["a", "b"],
                                        "when_to_use": "429"})
        assert "promote-procedure" in out
        out = record_note.invoke({"text": "假设 X", "kind": "hypothesis"})
        assert "Note #" in out
        store = MemoryStore(tmp_path)
        assert store.recent_decisions("main")[0]["text"] == "决定 A"
        assert store.draft_procedures()[0]["name"] == "drill"
        assert store.open_notes("main")[0]["kind"] == "hypothesis"
        store.close()

    def test_tool_validation_errors_are_strings(self):
        assert add_task.invoke({"text": "x", "priority": "urgent"}).startswith("Error")
        assert record_note.invoke({"text": "x", "kind": "banana"}).startswith("Error")
        assert propose_procedure.invoke(
            {"name": "x", "steps": [], "when_to_use": "y"}).startswith("Error")

    def test_tools_respect_thread_context(self, tmp_path):
        set_memory_context("strategy-a", None)
        add_task.invoke({"text": "thread scoped"})
        store = MemoryStore(tmp_path)
        assert store.open_tasks("strategy-a")[0]["text"] == "thread scoped"
        assert store.open_tasks("main") == []
        store.close()

    def test_set_note_status_tool(self, tmp_path):
        record_note.invoke({"text": "假设 X", "kind": "hypothesis"})
        out = set_note_status.invoke({"note_id": 1, "status": "rejected"})
        assert isinstance(out, str) and "rejected" in out
        assert set_note_status.invoke({"note_id": 999, "status": "folded"}) == "Note #999 not found."
        assert set_note_status.invoke({"note_id": 1, "status": "banana"}).startswith("Error")
        store = MemoryStore(tmp_path)
        assert store.open_notes("main") == []
        assert store.all_notes("main")[0]["status"] == "rejected"
        store.close()

    def test_set_note_status_in_write_tool_names(self):
        from quant_llm_wiki.agent.memory.tools import MEMORY_WRITE_TOOL_NAMES
        assert "set_note_status" in MEMORY_WRITE_TOOL_NAMES


# ---------------------------------------------------------------------------
# recall.py preamble
# ---------------------------------------------------------------------------


class TestPreamble:
    def test_empty_memory_gives_empty_preamble(self, tmp_path):
        store = MemoryStore(tmp_path)
        wf.ensure_workflow(tmp_path)
        assert compose_preamble(tmp_path, store, "main") == ""
        store.close()

    def test_preamble_contains_all_sections(self, tmp_path):
        store = MemoryStore(tmp_path)
        wf.ensure_workflow(tmp_path)
        wf.write_section(tmp_path, "Current Handoff", "先看 429 修复")
        store.add_task("open task A", "main")
        store.record_decision("decision B", "main")
        store.record_note("hypothesis C", "main", kind="hypothesis")
        text = compose_preamble(tmp_path, store, "main")
        for needle in ("先看 429 修复", "open task A", "decision B",
                       "hypothesis C", "工作记忆"):
            assert needle in text
        store.close()

    def test_preamble_token_budget_truncates(self, tmp_path):
        store = MemoryStore(tmp_path)
        wf.ensure_workflow(tmp_path)
        wf.write_section(tmp_path, "Current Handoff", "x" * 9000)
        text = compose_preamble(tmp_path, store, "main", token_budget=100)
        assert len(text) < 1000
        assert "truncated" in text
        store.close()

    def test_preamble_thread_scoped(self, tmp_path):
        store = MemoryStore(tmp_path)
        wf.ensure_workflow(tmp_path)
        store.add_task("A-only task", "A")
        assert "A-only task" not in compose_preamble(tmp_path, store, "B")
        store.close()


# ---------------------------------------------------------------------------
# hooks.py — lifecycle + significance gating
# ---------------------------------------------------------------------------


class TestMemorySession:
    def test_session_lifecycle_records_events(self, tmp_path):
        session = MemorySession.start(tmp_path, thread="main")
        session.on_user_prompt("hello")
        session.on_tool_result("audit_wiki", "clean")
        session.on_session_end()
        store = MemoryStore(tmp_path)
        row = store.conn.execute("SELECT * FROM sessions").fetchone()
        assert row["status"] == "closed" and row["summary"]
        types = [r["event_type"] for r in store.session_events(row["id"])]
        assert types == ["session_start", "prompt", "tool_result", "session_end"]
        store.close()

    def test_read_only_session_does_not_touch_workflow_md(self, tmp_path):
        session = MemorySession.start(tmp_path, thread="main")
        before = wf.workflow_path(tmp_path).read_bytes()
        session.on_user_prompt("知识库健康吗")
        session.on_tool_result("audit_wiki", "clean")
        session.on_tool_result("query_knowledge_base", "answer")
        session.on_session_end()
        assert wf.workflow_path(tmp_path).read_bytes() == before
        assert wf.read_sections(tmp_path)["Recent Sessions"] == ""

    def test_significant_session_writes_recent_sessions(self, tmp_path):
        session = MemorySession.start(tmp_path, thread="main")
        session.on_user_prompt("入库")
        session.on_tool_result("ingest_article", "2 ingested")
        session.on_session_end()
        body = wf.read_sections(tmp_path)["Recent Sessions"]
        assert "thread: main" in body and "ingest_article" in body

    def test_memory_tool_use_counts_as_significant(self, tmp_path):
        session = MemorySession.start(tmp_path, thread="main")
        session.on_tool_result("record_note", "Note #1 recorded")
        session.on_session_end()
        assert wf.read_sections(tmp_path)["Recent Sessions"] != ""

    def test_corrupt_sqlite_returns_none_not_crash(self, tmp_path):
        db = memory_root(tmp_path) / "memory.sqlite"
        db.parent.mkdir(parents=True)
        db.write_bytes(b"this is not a sqlite file at all" * 10)
        assert MemorySession.start(tmp_path) is None

    def test_jsonl_debug_only_when_flag_set(self, tmp_path, monkeypatch):
        session = MemorySession.start(tmp_path, thread="main")
        session.on_user_prompt("no jsonl")
        session.on_session_end()
        assert not (memory_root(tmp_path) / "events").exists()
        monkeypatch.setenv("MEMORY_DEBUG_JSONL", "1")
        session = MemorySession.start(tmp_path, thread="main")
        session.on_user_prompt("with jsonl")
        session.on_session_end()
        files = list((memory_root(tmp_path) / "events").glob("*.jsonl"))
        assert len(files) == 1
        lines = [json.loads(ln) for ln in files[0].read_text(encoding="utf-8").splitlines()]
        assert any(e["type"] == "prompt" for e in lines)

    def test_new_thread_forks_date_stamped(self, tmp_path):
        s1 = MemorySession.start(tmp_path, thread="idea")
        s1.on_session_end()
        s2 = MemorySession.start(tmp_path, new_thread=True)
        assert s2.thread_id.startswith("idea@")
        s2.on_session_end()

    def test_resumes_most_recent_thread(self, tmp_path):
        s1 = MemorySession.start(tmp_path, thread="alpha")
        s1.on_session_end()
        s2 = MemorySession.start(tmp_path)
        assert s2.thread_id == "alpha"
        s2.on_session_end()

    def test_summarizer_updates_handoff_unless_hand_edited(self, tmp_path, monkeypatch):
        fake = {"session_summary": "做了一件事", "new_decisions": [],
                "new_tasks": ["follow up"], "updated_handoff": "下次先看 X",
                "updated_next_steps": ["step n"]}
        monkeypatch.setattr("quant_llm_wiki.agent.memory.summarizer._llm_summarize",
                            lambda events_text: fake)
        session = MemorySession.start(tmp_path, thread="main", want_summary=True)
        session.on_user_prompt("做事")
        session.on_session_end()
        sections = wf.read_sections(tmp_path)
        assert sections["Current Handoff"] == "下次先看 X"
        assert "step n" in sections["Next Steps"]
        assert "做了一件事" in sections["Recent Sessions"]
        store = MemoryStore(tmp_path)
        assert store.open_tasks("main")[0]["text"] == "follow up"
        store.close()

        # Hand-edit handoff mid-session → summarizer must not clobber it.
        session = MemorySession.start(tmp_path, thread="main", want_summary=True)
        session.on_user_prompt("再做事")
        wf.write_section(tmp_path, "Current Handoff", "人工改的，别动")
        session.on_session_end()
        assert wf.read_sections(tmp_path)["Current Handoff"] == "人工改的，别动"
