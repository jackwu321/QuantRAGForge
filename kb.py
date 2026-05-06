"""kb.py — unified CLI for the Karpathy-shaped knowledge base.

Three durable verbs (ingest, query, lint) plus two internal operations
(compile, embed). All commands are thin dispatchers that import the existing
library modules and call their entry points; no business logic lives here.

Layout (this worktree):
    raw/      — incoming source articles (one dir per article)
    wiki/     — LLM-built Markdown memory: INDEX.md, concepts/, sources/, state.json
    schema/   — concept-schema.md, source-schema.md, wiki-structure.md, operations.md
    vector_store/ — ChromaDB substrate, used as fallback only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> int:
    import ingest_source

    if args.url:
        out = ingest_source.dispatch_url(
            args.url, content_type=args.content_type, force=args.force
        )
        print(f"Ingested: {out}")
    elif args.url_list:
        results = ingest_source.dispatch_url_list(
            Path(args.url_list).expanduser().resolve(),
            content_type=args.content_type,
            force=args.force,
        )
        ok = sum(1 for r in results if r.success)
        print(f"Ingested: {ok}/{len(results)}")
    elif args.html_file:
        out = ingest_source.dispatch_html_file(
            Path(args.html_file).expanduser().resolve(), content_type=args.content_type
        )
        print(f"Ingested HTML: {out}")
    elif args.pdf_file:
        out = ingest_source.dispatch_pdf_file(
            Path(args.pdf_file).expanduser().resolve(), content_type=args.content_type
        )
        print(f"Ingested PDF: {out}")
    elif args.pdf_url:
        out = ingest_source._dispatch_pdf_url(
            args.pdf_url, content_type=args.content_type, force=args.force
        )
        print(f"Ingested PDF URL: {out}")
    else:
        print("error: provide one of --url / --url-list / --html-file / --pdf-file / --pdf-url", file=sys.stderr)
        return 2

    if not args.no_compile:
        rc = cmd_compile(argparse.Namespace(mode="incremental", verbose=False, kb_root=str(ROOT)))
        if rc != 0:
            return rc
        rc = cmd_embed(argparse.Namespace(force=False, dry_run=False, kb_root=str(ROOT)))
        if rc != 0:
            return rc
    return 0


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def cmd_query(args: argparse.Namespace) -> int:
    """Run a query against the wiki-first KB. Wiki concepts surface first;
    vector retrieval is fallback substrate only.
    """
    forwarded = [
        args.mode,
        "--query", args.query,
        "--kb-root", str(Path(args.kb_root).expanduser().resolve()),
    ]
    if args.top_k:
        forwarded.extend(["--top-k", str(args.top_k)])
    if args.dry_run:
        forwarded.append("--dry-run")
    if args.output_file:
        forwarded.extend(["--output-file", args.output_file])
    if args.retrieval:
        forwarded.extend(["--retrieval", args.retrieval])

    # Save argv, swap, and call brainstorm_from_kb.main()
    import quant_llm_wiki.query.brainstorm as brainstorm_from_kb
    original_argv = sys.argv[:]
    sys.argv = ["kb query"] + forwarded
    try:
        rc = brainstorm_from_kb.main()
    finally:
        sys.argv = original_argv

    # Step 7 hook: file the answer back into wiki/queries/ unless --no-file-back.
    # Implemented in wiki_maintain.append_query_log; here we just call it best-effort.
    if not args.no_file_back and rc == 0:
        try:
            from wiki_maintain import append_query_log
            append_query_log(
                kb_root=Path(args.kb_root).expanduser().resolve(),
                query=args.query,
                mode=args.mode,
            )
        except ImportError:
            pass  # wiki_maintain not yet available (Step 6)
        except Exception as exc:
            print(f"warning: query feedback skipped — {exc}", file=sys.stderr)
    return rc


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------


def cmd_lint(args: argparse.Namespace) -> int:
    from wiki_lint import lint_wiki

    kb_root = Path(args.kb_root).expanduser().resolve()
    report = lint_wiki(kb_root)
    print(report.summary())
    for issue in report.issues:
        print(f"  [{issue.severity}] {issue.kind}: {issue.message} ({issue.path})")

    if args.fix:
        try:
            from wiki_lint import auto_fix
        except ImportError:
            print("error: --fix requires Step 5 (auto_fix) to be implemented.", file=sys.stderr)
            return 1
        fixed = auto_fix(kb_root, report)
        print(f"\nauto-fixed {fixed} issue(s).")

    if args.maintain:
        try:
            from wiki_maintain import run_maintenance
        except ImportError:
            print("error: --maintain requires Step 6 (wiki_maintain) to be implemented.", file=sys.stderr)
            return 1
        result = run_maintenance(kb_root, apply=args.apply)
        print(f"\nmaintenance: {result.summary()}")

    return 0 if report.ok_for_brainstorm() else 1


# ---------------------------------------------------------------------------
# compile (internal)
# ---------------------------------------------------------------------------


def cmd_compile(args: argparse.Namespace) -> int:
    from wiki_compile import compile_wiki
    from quant_llm_wiki.shared import DEFAULT_SOURCE_DIRS

    kb_root = Path(getattr(args, "kb_root", str(ROOT))).expanduser().resolve()
    report = compile_wiki(
        kb_root=kb_root,
        mode=getattr(args, "mode", "incremental"),
        dry_run=getattr(args, "dry_run", False),
        source_dirs=DEFAULT_SOURCE_DIRS,
        verbose=getattr(args, "verbose", False),
    )
    print(report.summary())
    if report.lint_summary:
        print(f"lint: {report.lint_summary}")
    if report.errors:
        for e in report.errors:
            print(f"  error: {e}", file=sys.stderr)
    return 0 if not report.errors else 1


# ---------------------------------------------------------------------------
# embed (internal)
# ---------------------------------------------------------------------------


def cmd_embed(args: argparse.Namespace) -> int:
    import quant_llm_wiki.embed as embed_knowledge_base
    forwarded = ["--kb-root", str(Path(args.kb_root).expanduser().resolve())]
    if args.force:
        forwarded.append("--force")
    if args.dry_run:
        forwarded.append("--dry-run")
    original_argv = sys.argv[:]
    sys.argv = ["kb embed"] + forwarded
    try:
        return embed_knowledge_base.main()
    finally:
        sys.argv = original_argv


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kb",
        description="Karpathy-shaped knowledge base CLI: ingest / query / lint / compile / embed.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="Ingest articles into raw/, then compile + embed unless --no-compile.")
    ing.add_argument("--url")
    ing.add_argument("--url-list")
    ing.add_argument("--html-file")
    ing.add_argument("--pdf-file")
    ing.add_argument("--pdf-url")
    ing.add_argument("--content-type")
    ing.add_argument("--force", action="store_true")
    ing.add_argument("--no-compile", action="store_true",
                     help="Skip the auto compile + embed after writing raw/.")
    ing.set_defaults(func=cmd_ingest)

    q = sub.add_parser("query", help="Wiki-first query (ask | brainstorm). RAG is fallback substrate only.")
    q.add_argument("--query", required=True)
    q.add_argument("--mode", choices=["ask", "brainstorm"], default="ask")
    q.add_argument("--kb-root", default=str(ROOT))
    q.add_argument("--top-k", type=int)
    q.add_argument("--retrieval", choices=["hybrid", "keyword", "vector"])
    q.add_argument("--dry-run", action="store_true")
    q.add_argument("--output-file")
    q.add_argument("--no-file-back", action="store_true",
                   help="Skip writing this query back into wiki/queries/.")
    q.set_defaults(func=cmd_query)

    lint = sub.add_parser("lint", help="Schema + health audit of the wiki.")
    lint.add_argument("--kb-root", default=str(ROOT))
    lint.add_argument("--fix", action="store_true",
                      help="Run an LLM auto-repair pass on schema-noncompliant offenders (Step 5).")
    lint.add_argument("--maintain", action="store_true",
                      help="Extend lint with maintenance: query-feedback, suggestions, gap analysis (Step 6).")
    lint.add_argument("--apply", action="store_true",
                      help="With --maintain: apply the proposed updates instead of previewing.")
    lint.set_defaults(func=cmd_lint)

    comp = sub.add_parser("compile", help="Compile wiki concept pages and source summaries from raw/.")
    comp.add_argument("--mode", choices=["incremental", "rebuild"], default="incremental")
    comp.add_argument("--dry-run", action="store_true")
    comp.add_argument("--verbose", action="store_true")
    comp.add_argument("--kb-root", default=str(ROOT))
    comp.set_defaults(func=cmd_compile)

    emb = sub.add_parser("embed", help="Refresh the ChromaDB substrate over raw/ + wiki/.")
    emb.add_argument("--force", action="store_true")
    emb.add_argument("--dry-run", action="store_true")
    emb.add_argument("--kb-root", default=str(ROOT))
    emb.set_defaults(func=cmd_embed)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
