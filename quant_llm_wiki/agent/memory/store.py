"""SQLite store for structured workflow memory.

One file per KB: `<kb_root>/.qlw/memory/memory.sqlite`. Tool-managed only —
the human-editable narrative lives in workflow.md, not here.

`procedures` is a draft pool for skills (status: draft/promoted/rejected);
the only runtime SOP system is the skill registry. There is no 'active'
procedure state on purpose.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from quant_llm_wiki.paths import memory_root

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY,
    thread_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'open'        -- 'open' | 'closed'
);
CREATE TABLE IF NOT EXISTS tasks(
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',       -- 'open' | 'done'
    priority TEXT NOT NULL DEFAULT 'normal',
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    thread_id TEXT NOT NULL,
    last_note TEXT
);
CREATE TABLE IF NOT EXISTS decisions(
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    rationale TEXT,
    created_at TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    session_id INTEGER
);
CREATE TABLE IF NOT EXISTS procedures(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    when_to_use TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',      -- 'draft' | 'promoted' | 'rejected'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,                  -- 'prompt'|'tool_result'|'session_start'|'session_end'
    summary TEXT,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS threads(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    last_session_id INTEGER,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'observation',  -- 'hypothesis' | 'direction' | 'observation'
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',       -- 'open' | 'parked' | 'folded' | 'rejected'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# External-content FTS tables + sync triggers. Created only when FTS5 exists.
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
    text, content='tasks', content_rowid='id');
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    text, rationale, content='decisions', content_rowid='id');
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    text, kind, content='notes', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS tasks_ai AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS tasks_au AFTER UPDATE ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO tasks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS tasks_ad AFTER DELETE ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(rowid, text, rationale)
    VALUES (new.id, new.text, coalesce(new.rationale, ''));
END;
CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, text, rationale)
    VALUES ('delete', old.id, old.text, coalesce(old.rationale, ''));
END;

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text, kind) VALUES (new.id, new.text, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text, kind) VALUES ('delete', old.id, old.text, old.kind);
    INSERT INTO notes_fts(rowid, text, kind) VALUES (new.id, new.text, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text, kind) VALUES ('delete', old.id, old.text, old.kind);
END;
"""

NOTE_KINDS = ("hypothesis", "direction", "observation")
NOTE_STATUSES = ("open", "parked", "folded", "rejected")
DEFAULT_THREAD = "main"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


class MemoryStore:
    """Thin transactional wrapper around memory.sqlite.

    Every public method is a single atomic transaction (sqlite autocommit
    per execute with isolation handled via `with self.conn`).
    """

    def __init__(self, kb_root: Path):
        self.kb_root = kb_root
        self.root = memory_root(kb_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "memory.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.fts_enabled = _fts5_available(self.conn)
        with self.conn:
            self.conn.executescript(_SCHEMA)
            if self.fts_enabled:
                self.conn.executescript(_FTS_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- threads / sessions --------------------------------------------------

    def touch_thread(self, thread_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO threads(id, name, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at",
                (thread_id, thread_id, _now()),
            )

    def most_recent_thread(self) -> str:
        row = self.conn.execute(
            "SELECT id FROM threads ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else DEFAULT_THREAD

    def open_session(self, thread_id: str) -> int:
        self.touch_thread(thread_id)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions(thread_id, started_at, status) VALUES (?, ?, 'open')",
                (thread_id, _now()),
            )
        return cur.lastrowid

    def close_session(self, session_id: int, summary: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET ended_at=?, status='closed', "
                "summary=coalesce(?, summary) WHERE id=?",
                (_now(), summary, session_id),
            )
            self.conn.execute(
                "UPDATE threads SET last_session_id=?, updated_at=? "
                "WHERE id=(SELECT thread_id FROM sessions WHERE id=?)",
                (session_id, _now(), session_id),
            )

    # -- events ---------------------------------------------------------------

    def add_event(self, session_id: int, event_type: str, summary: str = "",
                  payload: dict | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO events(session_id, ts, event_type, summary, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, _now(), event_type, summary,
                 json.dumps(payload, ensure_ascii=False) if payload is not None else None),
            )
        return cur.lastrowid

    def session_events(self, session_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()

    # -- tasks ----------------------------------------------------------------

    def add_task(self, text: str, thread_id: str, priority: str = "normal") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO tasks(text, priority, opened_at, thread_id) VALUES (?, ?, ?, ?)",
                (text, priority, _now(), thread_id),
            )
        return cur.lastrowid

    def complete_task(self, task_id: int, note: str | None = None) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE tasks SET status='done', closed_at=?, last_note=coalesce(?, last_note) "
                "WHERE id=? AND status='open'",
                (_now(), note, task_id),
            )
        return cur.rowcount > 0

    def open_tasks(self, thread_id: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if thread_id is None:
            return self.conn.execute(
                "SELECT * FROM tasks WHERE status='open' ORDER BY opened_at LIMIT ?",
                (limit,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM tasks WHERE status='open' AND thread_id=? ORDER BY opened_at LIMIT ?",
            (thread_id, limit)).fetchall()

    def all_tasks(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks ORDER BY opened_at DESC LIMIT ?", (limit,)).fetchall()

    # -- decisions ------------------------------------------------------------

    def record_decision(self, text: str, thread_id: str, rationale: str | None = None,
                        session_id: int | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO decisions(text, rationale, created_at, thread_id, session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (text, rationale, _now(), thread_id, session_id),
            )
        return cur.lastrowid

    def recent_decisions(self, thread_id: str | None = None, limit: int = 10) -> list[sqlite3.Row]:
        if thread_id is None:
            return self.conn.execute(
                "SELECT * FROM decisions ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM decisions WHERE thread_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (thread_id, limit)).fetchall()

    # -- procedures (skill draft pool) ----------------------------------------

    def propose_procedure(self, name: str, when_to_use: str, steps: list[str]) -> int:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO procedures(name, when_to_use, steps_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'draft', ?, ?)",
                (name, when_to_use, json.dumps(steps, ensure_ascii=False), now, now),
            )
        return cur.lastrowid

    def get_procedure(self, proc_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM procedures WHERE id=?", (proc_id,)).fetchone()

    def set_procedure_status(self, proc_id: int, status: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE procedures SET status=?, updated_at=? WHERE id=?",
                (status, _now(), proc_id),
            )
        return cur.rowcount > 0

    def draft_procedures(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM procedures WHERE status='draft' ORDER BY id").fetchall()

    # -- notes (research-process state; not wiki knowledge) --------------------

    def record_note(self, text: str, thread_id: str, kind: str = "observation") -> int:
        if kind not in NOTE_KINDS:
            raise ValueError(f"kind must be one of {NOTE_KINDS}")
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO notes(thread_id, kind, text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (thread_id, kind, text, now, now),
            )
        return cur.lastrowid

    def set_note_status(self, note_id: int, status: str) -> bool:
        if status not in NOTE_STATUSES:
            raise ValueError(f"status must be one of {NOTE_STATUSES}")
        with self.conn:
            cur = self.conn.execute(
                "UPDATE notes SET status=?, updated_at=? WHERE id=?",
                (status, _now(), note_id),
            )
        return cur.rowcount > 0

    def open_notes(self, thread_id: str, limit: int = 5) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM notes WHERE status='open' AND thread_id=? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (thread_id, limit)).fetchall()

    def all_notes(self, thread_id: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
        if thread_id is None:
            return self.conn.execute(
                "SELECT * FROM notes ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM notes WHERE thread_id=? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (thread_id, limit)).fetchall()
