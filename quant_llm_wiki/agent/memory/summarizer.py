"""Opt-in LLM session summarizer. Runs only with --summary / MEMORY_AUTO_SUMMARY=1.

Reads the session's compressed events, asks the LLM for a structured update,
and applies it: narrative summary (returned to the caller for sessions +
Recent Sessions), Current Handoff replace (sha-guarded — a hand-edited
handoff is never clobbered), Next Steps merge, deduplicated decision/task
inserts.
"""
from __future__ import annotations

import json

from quant_llm_wiki.agent.memory import workflow as wf

_SYSTEM = (
    "你是知识库 agent 的会话总结器。基于事件日志输出 JSON："
    '{"session_summary": "2-4 句中文叙述", "new_decisions": [{"text":..., "rationale":...}], '
    '"new_tasks": ["..."], "updated_handoff": "1-3 句，下个会话先看什么", '
    '"updated_next_steps": ["..."]} '
    "只提取明确发生的事，不要发明决定或任务；没有就给空列表/空串。只输出 JSON。"
)


def _llm_summarize(events_text: str) -> dict:
    from quant_llm_wiki.shared import get_llm_config, post_llm_json
    from quant_llm_wiki.enrich import parse_json_response

    _, _, model = get_llm_config()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"事件日志：\n{events_text}"},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    data = post_llm_json("/chat/completions", payload)
    return parse_json_response(data["choices"][0]["message"]["content"])


def summarize_session(session) -> str | None:
    """Apply LLM summary for a MemorySession. Returns the narrative summary
    (for sessions.summary + Recent Sessions) or None on empty output."""
    events = session.store.session_events(session.session_id)
    lines = [f"[{e['event_type']}] {e['summary'] or ''}" for e in events]
    if not lines:
        return None
    result = _llm_summarize("\n".join(lines))

    summary = (result.get("session_summary") or "").strip()

    for d in result.get("new_decisions") or []:
        text = (d.get("text") or "").strip() if isinstance(d, dict) else str(d).strip()
        if not text:
            continue
        rationale = d.get("rationale") if isinstance(d, dict) else None
        existing = {r["text"] for r in session.store.recent_decisions(session.thread_id, limit=50)}
        if text not in existing:
            session.store.record_decision(text, session.thread_id, rationale,
                                          session.session_id)

    open_texts = {r["text"] for r in session.store.open_tasks(session.thread_id, limit=100)}
    for t in result.get("new_tasks") or []:
        t = str(t).strip()
        if t and t not in open_texts:
            session.store.add_task(t, session.thread_id)

    handoff = (result.get("updated_handoff") or "").strip()
    if handoff:
        if wf.section_sha(session.kb_root, "Current Handoff") == session.handoff_sha_at_start:
            wf.write_section(session.kb_root, "Current Handoff", handoff)
        else:
            import sys
            print("[memory] Current Handoff was hand-edited during the session; "
                  "leaving it untouched.", file=sys.stderr)

    steps = [str(s).strip() for s in (result.get("updated_next_steps") or []) if str(s).strip()]
    if steps:
        wf.merge_next_steps(session.kb_root, steps)

    return summary or None
