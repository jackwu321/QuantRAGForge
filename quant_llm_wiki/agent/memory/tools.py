"""Six memory agent tools. Thin: validation + atomic SQL + ack. No LLM calls.

All tools return plain strings (GLM-4.7 yields empty final answers on
dict-typed ToolMessages — see skill_registry.py).

Thread/session context is injected by the session lifecycle (hooks/CLI) via
`set_memory_context`; tools resolve kb_root at call time like every other
agent tool.
"""
from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from quant_llm_wiki.agent.memory.store import DEFAULT_THREAD, NOTE_KINDS, MemoryStore
from quant_llm_wiki.paths import resolve_kb_root

_context: dict = {"thread_id": DEFAULT_THREAD, "session_id": None}


def set_memory_context(thread_id: str, session_id: int | None = None) -> None:
    _context["thread_id"] = thread_id
    _context["session_id"] = session_id


def get_memory_context() -> dict:
    return dict(_context)


def _store() -> MemoryStore:
    return MemoryStore(resolve_kb_root(None))


@tool
def record_decision(text: str, rationale: Optional[str] = None) -> str:
    """Record a decision made in this conversation (e.g. "用 FTS5，LIKE 兜底").

    Use only when the user states or confirms a decision — never to log
    routine tool activity."""
    store = _store()
    try:
        did = store.record_decision(text, _context["thread_id"], rationale,
                                    _context["session_id"])
        return f"Decision #{did} recorded."
    finally:
        store.close()


@tool
def add_task(text: str, priority: str = "normal") -> str:
    """Add an open workflow task (e.g. "继续 full-ingest：等用户 review 决定").

    priority: 'high' | 'normal' | 'low'."""
    if priority not in ("high", "normal", "low"):
        return "Error: priority must be one of high / normal / low."
    store = _store()
    try:
        tid = store.add_task(text, _context["thread_id"], priority)
        return f"Task #{tid} added (open, {priority})."
    finally:
        store.close()


@tool
def complete_task(task_id: int, note: Optional[str] = None) -> str:
    """Mark an open task as done, optionally with a closing note."""
    store = _store()
    try:
        if store.complete_task(task_id, note):
            return f"Task #{task_id} marked done."
        return f"Task #{task_id} not found or already done."
    finally:
        store.close()


@tool
def list_open_tasks() -> str:
    """List open workflow tasks for the current thread."""
    store = _store()
    try:
        rows = store.open_tasks(_context["thread_id"])
        if not rows:
            return "No open tasks."
        return "\n".join(
            f"#{r['id']} [{r['priority']}] {r['text']} (opened {r['opened_at'][:10]})"
            for r in rows)
    finally:
        store.close()


@tool
def propose_procedure(name: str, steps: list[str], when_to_use: str) -> str:
    """Save a reusable procedure the user described as a DRAFT in the skill
    draft pool. Drafts are inert until the user promotes one to a real skill.

    Use only when the user explicitly describes a repeatable flow
    ("以后这种情况按这个流程做")."""
    if not steps or not all(isinstance(s, str) and s.strip() for s in steps):
        return "Error: steps must be a non-empty list of step descriptions."
    store = _store()
    try:
        pid = store.propose_procedure(name, when_to_use, steps)
        return (f"Procedure draft #{pid} ('{name}') saved to the skill draft pool. "
                f"运行 `qlw memory promote-procedure {pid}` 可将其生成为正式 skill "
                f"(.qlw/skills/)，或 `qlw memory reject-draft {pid}` 丢弃。")
    finally:
        store.close()


@tool
def record_note(text: str, kind: str = "observation") -> str:
    """Record research-process state for the current thread: a hypothesis,
    a strategy direction, or an observation.

    kind: 'hypothesis' | 'direction' | 'observation'. Notes hold unstable
    research state — never write this kind of content into the wiki."""
    if kind not in NOTE_KINDS:
        return f"Error: kind must be one of {' / '.join(NOTE_KINDS)}."
    store = _store()
    try:
        nid = store.record_note(text, _context["thread_id"], kind)
        return f"Note #{nid} ({kind}) recorded for thread '{_context['thread_id']}'."
    finally:
        store.close()


MEMORY_TOOLS = [
    record_decision,
    add_task,
    complete_task,
    list_open_tasks,
    propose_procedure,
    record_note,
]

# Memory tools that count as "significant" write actions for the
# workflow.md session-log gate (see hooks.py).
MEMORY_WRITE_TOOL_NAMES = {
    "record_decision", "add_task", "complete_task", "propose_procedure", "record_note",
}
