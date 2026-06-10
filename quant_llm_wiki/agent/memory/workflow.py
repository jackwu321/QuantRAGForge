"""Section-aware IO for workflow.md — the narrative, human-editable layer.

workflow.md is the source of truth for working memory (handoff / next steps /
blockers) plus a capped narrative session log. Hand-edits always win: writers
replace exactly one section at a time and the summarizer checks a section
hash before overwriting Current Handoff.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from quant_llm_wiki.paths import memory_root

SECTIONS = ("Current Handoff", "Next Steps", "Blockers", "Recent Sessions")
DEFAULT_RECENT_KEEP = 10

_HEADER_RE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


def workflow_path(kb_root: Path) -> Path:
    return memory_root(kb_root) / "workflow.md"


def _skeleton(kb_root: Path) -> str:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [f"# Agent Workflow", f"_KB: {kb_root} · last updated: {ts}_", ""]
    for s in SECTIONS:
        lines += [f"## {s}", ""]
    return "\n".join(lines)


def ensure_workflow(kb_root: Path) -> Path:
    path = workflow_path(kb_root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_skeleton(kb_root), encoding="utf-8")
    return path


def read_sections(kb_root: Path) -> dict[str, str]:
    """Section name -> body text (stripped). Missing sections map to ''."""
    path = workflow_path(kb_root)
    result = {s: "" for s in SECTIONS}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8")
    matches = list(_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if name in result:
            result[name] = text[m.end():end].strip("\n").strip()
    return result


def section_sha(kb_root: Path, section: str) -> str:
    return hashlib.sha256(read_sections(kb_root)[section].encode("utf-8")).hexdigest()


def _touch_updated_line(text: str) -> str:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return re.sub(r"^_KB: (.+?) · last updated: .*?_$",
                  rf"_KB: \1 · last updated: {ts}_", text, count=1, flags=re.MULTILINE)


def write_section(kb_root: Path, section: str, body: str) -> None:
    """Replace exactly one section's body, leaving every other byte alone."""
    if section not in SECTIONS:
        raise ValueError(f"unknown section: {section}")
    path = ensure_workflow(kb_root)
    text = path.read_text(encoding="utf-8")
    matches = list(_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        if m.group(1) != section:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body_block = body.strip("\n")
        replacement = m.group(0) + "\n" + (body_block + "\n\n" if body_block else "\n")
        text = text[:m.start()] + replacement + text[end:]
        path.write_text(_touch_updated_line(text), encoding="utf-8")
        return
    # Section header missing (hand-trimmed file): append it at the end.
    body_block = body.strip("\n")
    text = text.rstrip("\n") + f"\n\n## {section}\n" + (body_block + "\n" if body_block else "")
    path.write_text(_touch_updated_line(text), encoding="utf-8")


def prepend_recent_session(kb_root: Path, entry_md: str,
                           keep: int = DEFAULT_RECENT_KEEP) -> None:
    """Prepend one `### ...` entry to Recent Sessions; prune beyond `keep`.

    Pruned entries are not lost — the full history stays in SQLite sessions.
    """
    current = read_sections(kb_root)["Recent Sessions"]
    entries = [e for e in re.split(r"(?=^### )", current, flags=re.MULTILINE) if e.strip()]
    entries.insert(0, entry_md.strip("\n") + "\n")
    body = "\n".join(e.rstrip("\n") + "\n" for e in entries[:keep])
    write_section(kb_root, "Recent Sessions", body)


def merge_next_steps(kb_root: Path, items: list[str]) -> None:
    """Append bullet items not already present (exact text match)."""
    current = read_sections(kb_root)["Next Steps"]
    existing = {ln.lstrip("- ").strip() for ln in current.splitlines() if ln.strip()}
    new = [it.strip() for it in items if it.strip() and it.strip() not in existing]
    if not new:
        return
    body = (current + "\n" if current else "") + "\n".join(f"- {it}" for it in new)
    write_section(kb_root, "Next Steps", body)


def session_entry(thread_id: str, summary: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"### {ts} (thread: {thread_id})\n{summary.strip()}"
