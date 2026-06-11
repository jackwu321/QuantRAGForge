"""Session lifecycle for workflow memory.

The agent CLI drives one `MemorySession` per run. Events are compressed
deterministically into SQLite; workflow.md's Recent Sessions is only written
when the session was *significant* (any write-action tool ran) or the LLM
summarizer is explicitly enabled — read-only Q&A must not turn workflow.md
into a click log.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_llm_wiki.agent.memory.store import DEFAULT_THREAD, MemoryStore
from quant_llm_wiki.agent.memory.tools import MEMORY_WRITE_TOOL_NAMES, set_memory_context
from quant_llm_wiki.agent.memory import workflow as wf
from quant_llm_wiki.agent.memory.recall import compose_preamble

# KB write tools whose use makes a session worth a narrative log entry.
KB_WRITE_TOOL_NAMES = {
    "ingest_article", "enrich_articles", "set_article_status",
    "set_concept_status", "compile_wiki", "embed_knowledge",
    "save_strategy_brief",
}
SIGNIFICANT_TOOL_NAMES = KB_WRITE_TOOL_NAMES | MEMORY_WRITE_TOOL_NAMES

_PAYLOAD_CAP = 4096


class MemorySession:
    """One agent run's memory lifecycle. Construct via `start()`."""

    def __init__(self, store: MemoryStore, kb_root: Path, thread_id: str,
                 session_id: int, want_summary: bool):
        self.store = store
        self.kb_root = kb_root
        self.thread_id = thread_id
        self.session_id = session_id
        self.want_summary = want_summary
        self.tools_seen: list[str] = []
        self.prompts_seen: list[str] = []
        self.handoff_sha_at_start = wf.section_sha(kb_root, "Current Handoff")
        self.closed = False
        from quant_llm_wiki.shared import get_memory_config
        self._debug_jsonl = get_memory_config()["debug_jsonl"]

    def _event(self, event_type: str, summary: str = "", payload: dict | None = None) -> None:
        self.store.add_event(self.session_id, event_type, summary, payload)
        if self._debug_jsonl:
            events_dir = self.store.root / "events"
            events_dir.mkdir(exist_ok=True)
            with open(events_dir / f"{self.session_id}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": event_type, "summary": summary,
                                     "payload": payload}, ensure_ascii=False) + "\n")

    # -- construction ----------------------------------------------------------

    @classmethod
    def start(cls, kb_root: Path, thread: str | None = None, new_thread: bool = False,
              want_summary: bool = False) -> "MemorySession | None":
        """Open a session. Returns None (memory disabled) if the store is
        unusable — a corrupt memory.sqlite must never break the agent."""
        try:
            store = MemoryStore(kb_root)
            wf.ensure_workflow(kb_root)
            thread_id = thread or store.most_recent_thread() or DEFAULT_THREAD
            if new_thread:
                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
                thread_id = f"{thread_id}@{stamp}"
            session_id = store.open_session(thread_id)
            store.add_event(session_id, "session_start", f"thread={thread_id}")
            set_memory_context(thread_id, session_id)
            return cls(store, kb_root, thread_id, session_id, want_summary)
        except Exception as exc:
            import sys
            print(f"[memory] disabled for this run ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            return None

    # -- read path ---------------------------------------------------------------

    def preamble(self) -> str:
        from quant_llm_wiki.shared import get_memory_config
        cfg = get_memory_config()
        return compose_preamble(self.kb_root, self.store, self.thread_id,
                                token_budget=cfg["preamble_token_budget"],
                                recent_n=cfg["recent_sessions_n"])

    # -- event hooks ---------------------------------------------------------------

    def on_user_prompt(self, text: str) -> None:
        self.prompts_seen.append(text)
        self._event("prompt", text[:200], {"text": text})

    def on_tool_result(self, name: str, result: str, error: str | None = None) -> None:
        self.tools_seen.append(name)
        summary = f"tool={name} " + ("error" if error else "ok")
        if error:
            summary += f": {error[:120]}"
        self._event("tool_result", summary,
                    {"tool": name, "ok": error is None,
                     "result": str(result)[:_PAYLOAD_CAP],
                     "error": error})

    def observe_messages(self, messages: list, start_index: int) -> None:
        """Record events from LangChain messages produced after start_index."""
        for m in messages[start_index:]:
            mtype = getattr(m, "type", None)
            if mtype == "tool":
                name = getattr(m, "name", None) or "unknown"
                content = str(getattr(m, "content", ""))
                is_err = getattr(m, "status", None) == "error"
                self.on_tool_result(name, content, content[:120] if is_err else None)

    # -- end of session ---------------------------------------------------------------

    @property
    def significant(self) -> bool:
        return any(t in SIGNIFICANT_TOOL_NAMES for t in self.tools_seen)

    def _deterministic_summary(self) -> str:
        tools = sorted(set(self.tools_seen))
        first = self.prompts_seen[0][:80] if self.prompts_seen else ""
        bits = [f"{len(self.prompts_seen)} prompt(s)"]
        if tools:
            bits.append("tools: " + ", ".join(tools))
        line = "; ".join(bits) + "."
        if first:
            line += f' First: "{first}"'
        return line

    def on_session_end(self, reason: str = "exit") -> None:
        if self.closed:
            return
        self.closed = True
        summary = self._deterministic_summary()
        self._event("session_end", reason)

        if self.want_summary:
            try:
                from quant_llm_wiki.agent.memory.summarizer import summarize_session
                llm_summary = summarize_session(self)
                if llm_summary:
                    summary = llm_summary
            except Exception as exc:
                import sys
                print(f"[memory] summarizer failed, falling back to deterministic "
                      f"summary ({type(exc).__name__}: {exc})", file=sys.stderr)

        self.store.close_session(self.session_id, summary)
        # workflow.md gate: significant sessions only (or explicit --summary).
        if self.significant or self.want_summary:
            from quant_llm_wiki.shared import get_memory_config
            keep = get_memory_config()["recent_sessions_keep"]
            wf.prepend_recent_session(
                self.kb_root, wf.session_entry(self.thread_id, summary), keep=keep)
        self.store.close()
