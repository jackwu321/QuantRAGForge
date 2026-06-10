"""`qlw memory` subcommands.

Inspection (status/show/tasks/decisions/notes/recall/audit), workflow.md
maintenance (clear-current), and the procedure draft pool lifecycle:
drafts → promote-procedure (generates a real .qlw/skills/<name>.md, the only
runtime SOP system) or reject-draft.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from quant_llm_wiki.paths import memory_root, resolve_kb_root


def _store(args):
    from quant_llm_wiki.agent.memory.store import MemoryStore
    return MemoryStore(resolve_kb_root(getattr(args, "kb_root", None)))


def _kb_root(args) -> Path:
    return resolve_kb_root(getattr(args, "kb_root", None))


def _cmd_status(args) -> int:
    store = _store(args)
    n_sessions = store.conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
    last = store.conn.execute(
        "SELECT thread_id, started_at FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    print(f"memory root : {store.root}")
    print(f"sessions    : {n_sessions}")
    print(f"last session: {last['started_at']} (thread: {last['thread_id']})" if last else "last session: —")
    print(f"open tasks  : {len(store.open_tasks())}")
    print(f"FTS5        : {'enabled' if store.fts_enabled else 'DEGRADED (LIKE fallback)'}")
    store.close()
    return 0


def _cmd_show(args) -> int:
    from quant_llm_wiki.agent.memory.workflow import ensure_workflow
    print(ensure_workflow(_kb_root(args)).read_text(encoding="utf-8"))
    return 0


def _cmd_tasks(args) -> int:
    store = _store(args)
    rows = store.all_tasks() if args.all else store.open_tasks()
    for r in rows:
        mark = "x" if r["status"] == "done" else " "
        print(f"[{mark}] #{r['id']} [{r['priority']}] {r['text']} (thread: {r['thread_id']})")
    if not rows:
        print("No tasks.")
    store.close()
    return 0


def _cmd_decisions(args) -> int:
    store = _store(args)
    rows = store.recent_decisions(limit=args.limit)
    for r in rows:
        line = f"#{r['id']} {r['created_at'][:10]} {r['text']}"
        if r["rationale"]:
            line += f" — {r['rationale']}"
        print(line)
    if not rows:
        print("No decisions.")
    store.close()
    return 0


def _cmd_notes(args) -> int:
    store = _store(args)
    rows = store.all_notes(thread_id=args.thread)
    if not args.all:
        rows = [r for r in rows if r["status"] == "open"]
    for r in rows:
        print(f"#{r['id']} [{r['kind']}/{r['status']}] (thread: {r['thread_id']}) {r['text']}")
    if not rows:
        print("No notes.")
    store.close()
    return 0


def _cmd_note_status(args) -> int:
    store = _store(args)
    try:
        ok = store.set_note_status(args.id, args.status)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        store.close()
        return 2
    print(f"Note #{args.id} → {args.status}" if ok else f"Note #{args.id} not found")
    store.close()
    return 0 if ok else 1


def _cmd_recall(args) -> int:
    from quant_llm_wiki.agent.memory.recall import recall
    store = _store(args)
    hits = recall(store, args.query)
    for h in hits:
        print(f"[{h['type']}] #{h['id']} {h['text']}" + (f" ({h['extra']})" if h["extra"] else ""))
    if not hits:
        print("No matches.")
    store.close()
    return 0


def _cmd_audit(args) -> int:
    kb_root = _kb_root(args)
    store = _store(args)
    problems = []
    tables = {r[0] for r in store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {"sessions", "tasks", "decisions", "procedures", "events", "threads", "notes"}
    missing = expected - tables
    if missing:
        problems.append(f"missing tables: {sorted(missing)}")
    print(f"schema      : {'ok' if not missing else 'INCOMPLETE'}")
    print(f"FTS5        : {'enabled' if store.fts_enabled else 'DEGRADED (LIKE fallback)'}")
    # KB isolation: memory must live under .qlw/, never inside wiki data dirs.
    mroot = memory_root(kb_root)
    for forbidden in ("wiki", "vector_store", "raw", "schema"):
        if (kb_root / forbidden) in mroot.parents:
            problems.append(f"memory root leaked into {forbidden}/")
    print(f"KB isolation: {'ok' if not any('leaked' in p for p in problems) else 'VIOLATED'}")
    open_sessions = store.conn.execute(
        "SELECT count(*) FROM sessions WHERE status='open'").fetchone()[0]
    if open_sessions:
        print(f"note        : {open_sessions} session(s) left open (crashed runs?)")
    store.close()
    if problems:
        for p in problems:
            print(f"problem: {p}", file=sys.stderr)
        return 1
    return 0


def _cmd_clear_current(args) -> int:
    from quant_llm_wiki.agent.memory import workflow as wf
    kb_root = _kb_root(args)
    for section in ("Current Handoff", "Next Steps", "Blockers"):
        wf.write_section(kb_root, section, "")
    print("Cleared Current Handoff / Next Steps / Blockers (SQLite untouched).")
    return 0


def _cmd_drafts(args) -> int:
    store = _store(args)
    rows = store.draft_procedures()
    for r in rows:
        steps = json.loads(r["steps_json"])
        print(f"#{r['id']} {r['name']} — when: {r['when_to_use']} ({len(steps)} steps)")
    if not rows:
        print("No drafts.")
    store.close()
    return 0


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9一-鿿]+", "-", name.lower()).strip("-")
    return slug or "procedure"


def _cmd_promote(args) -> int:
    """Generate .qlw/skills/<name>.md from a draft and validate it loads."""
    from quant_llm_wiki.agent.skill_registry import load_skill_registry
    kb_root = _kb_root(args)
    store = _store(args)
    row = store.get_procedure(args.id)
    if row is None or row["status"] != "draft":
        print(f"error: draft #{args.id} not found (see `qlw memory drafts`)", file=sys.stderr)
        store.close()
        return 2

    slug = _slugify(args.name or row["name"])
    skills_dir = kb_root / ".qlw" / "skills"
    skill_path = skills_dir / f"{slug}.md"
    if skill_path.exists() and not args.force:
        print(f"error: {skill_path} already exists (use --force to overwrite)", file=sys.stderr)
        store.close()
        return 2

    steps = json.loads(row["steps_json"])
    steps_md = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))
    when = row["when_to_use"].replace('"', "'")
    content = (
        "---\n"
        f"name: {slug}\n"
        f"description: {when}\n"
        "version: 1\n"
        "triggers:\n"
        + "".join(f"  - {t}\n" for t in dict.fromkeys([row["name"], row["when_to_use"]]))
        + "requires_user_decision: false\n"
        "tools_used: []\n"
        "---\n\n"
        f"## When to use\n{row['when_to_use']}\n\n"
        f"## Steps\n{steps_md}\n\n"
        "## Notes\n"
        f"- Promoted from procedure draft #{row['id']} ({row['created_at'][:10]}); "
        "review and refine triggers / tools_used by hand.\n"
    )
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(content, encoding="utf-8")

    reg = load_skill_registry(kb_root)
    errors = [e for e in reg["_errors"] if e["path"] == str(skill_path)]
    if errors or slug not in {s["name"] for s in reg["skills"]}:
        skill_path.unlink(missing_ok=True)
        print(f"error: generated skill failed validation: "
              f"{errors[0]['error'] if errors else 'not in registry'}", file=sys.stderr)
        store.close()
        return 1

    store.set_procedure_status(args.id, "promoted")
    store.close()
    print(f"Draft #{args.id} promoted → {skill_path}")
    print("建议人工补全 frontmatter 的 triggers / tools_used，再用 list_skills 验证。")
    return 0


def _cmd_reject(args) -> int:
    store = _store(args)
    row = store.get_procedure(args.id)
    if row is None or row["status"] != "draft":
        print(f"error: draft #{args.id} not found", file=sys.stderr)
        store.close()
        return 2
    store.set_procedure_status(args.id, "rejected")
    store.close()
    print(f"Draft #{args.id} rejected.")
    return 0


def register(parser: argparse.ArgumentParser) -> None:
    """Attach `qlw memory ...` subcommands. Called by quant_llm_wiki.cli."""
    parser.add_argument("--kb-root", default=None,
                        help="Knowledge base root (default: $QLW_KB_ROOT or cwd).")
    sub = parser.add_subparsers(dest="memory_cmd", required=True)

    sub.add_parser("status", help="Memory health summary.").set_defaults(func=_cmd_status)
    sub.add_parser("show", help="Print workflow.md.").set_defaults(func=_cmd_show)

    p = sub.add_parser("tasks", help="List open tasks (--all for everything).")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=_cmd_tasks)

    p = sub.add_parser("decisions", help="Recent decisions.")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=_cmd_decisions)

    p = sub.add_parser("notes", help="Research notes (open by default).")
    p.add_argument("--all", action="store_true")
    p.add_argument("--thread", default=None)
    p.set_defaults(func=_cmd_notes)

    p = sub.add_parser("note-status", help="Set a note's status.")
    p.add_argument("id", type=int)
    p.add_argument("status", choices=("open", "parked", "folded"))
    p.set_defaults(func=_cmd_note_status)

    p = sub.add_parser("recall", help="Search tasks + decisions + notes.")
    p.add_argument("query")
    p.set_defaults(func=_cmd_recall)

    sub.add_parser("audit", help="Schema / FTS5 / KB-isolation audit.").set_defaults(func=_cmd_audit)
    sub.add_parser("clear-current",
                   help="Clear Current Handoff / Next Steps / Blockers.").set_defaults(func=_cmd_clear_current)
    sub.add_parser("drafts", help="List procedure drafts (skill draft pool).").set_defaults(func=_cmd_drafts)

    p = sub.add_parser("promote-procedure",
                       help="Promote a draft into a real .qlw/skills/<name>.md skill.")
    p.add_argument("id", type=int)
    p.add_argument("--name", default=None, help="Override the skill slug.")
    p.add_argument("--force", action="store_true", help="Overwrite an existing skill file.")
    p.set_defaults(func=_cmd_promote)

    p = sub.add_parser("reject-draft", help="Reject a procedure draft.")
    p.add_argument("id", type=int)
    p.set_defaults(func=_cmd_reject)
