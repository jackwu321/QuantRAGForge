from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

# Ensure project root is importable
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_llm_wiki.shared import (
    ROOT as KB_ROOT,
    DEFAULT_SOURCE_DIRS,
    discover_article_dirs,
    load_notes,
    parse_frontmatter,
    filter_notes,
    parse_csv_arg,
    find_rejected_source,
    add_rejected_source,
)


# ---------------------------------------------------------------------------
# Tool 1: ingest_article
# ---------------------------------------------------------------------------


@tool
def ingest_article(
    url: Optional[str] = None,
    urls: Optional[str] = None,
    url_list_file: Optional[str] = None,
    html_file: Optional[str] = None,
    pdf_file: Optional[str] = None,
    pdf_url: Optional[str] = None,
    content_type: Optional[str] = None,
    force: bool = False,
) -> str:
    """Ingest articles into the knowledge base from various sources.

    Accepts ONE of the following (in priority order):
    - url: A single URL (auto-detected: WeChat / web / PDF)
    - urls: Multiple URLs (newline/comma separated; each auto-detected)
    - url_list_file: Path to a .txt file with one URL per line
    - html_file: Path to a locally saved HTML file (WeChat-style)
    - pdf_file: Path to a local PDF file
    - pdf_url: A direct URL to a PDF document

    Set force=True to re-ingest articles that already exist."""
    import ingest_source
    from quant_llm_wiki.ingest.wechat import (
        extract_article_data,
        write_article,
        detect_blocked_wechat_page,
        DuplicateArticleError,
    )

    # Single PDF file
    if pdf_file:
        try:
            out = ingest_source.dispatch_pdf_file(pdf_file, content_type=content_type)
            return f"Ingested PDF: {out}"
        except Exception as exc:
            return f"Error ingesting PDF file {pdf_file}: {exc}"

    # Single PDF URL
    if pdf_url:
        try:
            out = ingest_source._dispatch_pdf_url(pdf_url, content_type=content_type, force=force)
            return f"Ingested PDF: {out}"
        except Exception as exc:
            return f"Error ingesting PDF URL {pdf_url}: {exc}"

    # Single HTML file (WeChat-style)
    if html_file and not url and not urls and not url_list_file:
        try:
            html_path = Path(html_file).expanduser().resolve()
            html = html_path.read_text(encoding="utf-8")
            detect_blocked_wechat_page(html)
            article = extract_article_data(html, "", None)
            if content_type:
                article.content_type = content_type
            out_dir = write_article(article, force=force)
            return f"Ingested HTML file successfully: {out_dir}"
        except DuplicateArticleError as exc:
            return f"Skipped (already exists): {exc}. Use force=True to re-ingest."
        except Exception as exc:
            return f"Error ingesting HTML file {html_file}: {exc}"

    # Collect URLs from the various input methods
    url_list: list[str] = []
    if url_list_file:
        try:
            url_list = [
                ln.strip()
                for ln in Path(url_list_file).expanduser().read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
        except Exception as exc:
            return f"Error reading URL list file {url_list_file}: {exc}"
        if not url_list:
            return f"No valid URLs found in {url_list_file}"
    elif urls:
        raw = urls.replace(",", "\n").replace(";", "\n").replace("，", "\n").replace("；", "\n")
        url_list = [u.strip() for u in raw.splitlines() if u.strip()]
    elif url:
        url_list = [url]
    else:
        return "Please provide one of: url, urls, url_list_file, html_file, pdf_file, pdf_url."

    results: list[str] = []
    success_count = 0
    skipped_count = 0
    rejected_warnings: list[str] = []
    for i, u in enumerate(url_list, start=1):
        rejected = find_rejected_source(source_url=u)
        if rejected and not force:
            reason = rejected.get("reason", "low value")
            title = rejected.get("title", "unknown")
            results.append(
                f"[{i}/{len(url_list)}] WARNING — previously rejected: \"{title}\" "
                f"(reason: {reason}). Use force=True to re-ingest."
            )
            rejected_warnings.append(u)
            continue
        try:
            out = ingest_source.dispatch_url(u, content_type=content_type, force=force)
            success_count += 1
            results.append(f"[{i}/{len(url_list)}] OK: {out}")
        except DuplicateArticleError as exc:
            skipped_count += 1
            results.append(f"[{i}/{len(url_list)}] SKIPPED (exists): {exc}")
        except Exception as exc:
            results.append(f"[{i}/{len(url_list)}] FAILED {u}: {exc}")

    fail_count = len(url_list) - success_count - skipped_count - len(rejected_warnings)
    parts = [f"{success_count} ingested"]
    if skipped_count:
        parts.append(f"{skipped_count} skipped (already exist)")
    if rejected_warnings:
        parts.append(f"{len(rejected_warnings)} previously rejected")
    if fail_count:
        parts.append(f"{fail_count} failed")
    return f"Result: {', '.join(parts)} (total {len(url_list)})\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Tool 2: enrich_articles
# ---------------------------------------------------------------------------


@tool
def enrich_articles(
    article_dir: Optional[str] = None,
    status_filter: str = "raw",
    force: bool = False,
    limit: Optional[int] = None,
) -> str:
    """Enrich articles with LLM-generated structured metadata (idea_blocks,
    transfer_targets, combination_hooks, failure_modes, etc.).
    Optionally specify a single article_dir, or process all articles matching
    the status_filter (default: raw).
    Use 'limit' to cap the number of articles processed (recommended for
    interactive use to avoid long waits).
    Articles are processed concurrently for speed (configurable via LLM_CONCURRENCY env var)."""
    from quant_llm_wiki.enrich import (
        discover_article_dirs as enrich_discover,
        run_enrich_batch,
        get_concurrency,
        ProcessResult,
    )

    args = argparse.Namespace(
        article_dir=article_dir,
        articles_root=str(KB_ROOT / "articles" / "raw"),
        status_filter=status_filter,
        force=force,
        dry_run=False,
        limit=limit,
        concurrency=None,
    )
    try:
        article_dirs = enrich_discover(args)
    except Exception as exc:
        return f"Error discovering articles: {exc}"

    if not article_dirs:
        return "No articles found matching the criteria."

    concurrency = get_concurrency(args)
    total = len(article_dirs)
    print(f"  Enriching {total} articles (concurrency={concurrency}) ...", flush=True)

    def _progress(i, t, result):
        status = "ok" if result.success else f"failed: {result.error}"
        print(f"  [{i}/{t}] {Path(result.article_dir).name}: {status}", flush=True)

    results = run_enrich_batch(article_dirs, args, concurrency, progress_callback=_progress)

    success = sum(1 for r in results if r.success)
    failed = [r for r in results if not r.success]
    lines = [f"Enrichment complete: {success}/{len(results)} succeeded."]
    for r in failed:
        lines.append(f"  Failed: {r.article_dir} — {r.error}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3: list_articles
# ---------------------------------------------------------------------------


@tool
def list_articles(source_dir: Optional[str] = None) -> str:
    """List articles in the knowledge base, grouped by stage (raw, reviewed,
    high-value). Shows title, content_type, brainstorm_value, and status."""
    source_dirs = parse_csv_arg(source_dir) if source_dir else ["raw", "reviewed", "high-value"]
    lines: list[str] = []
    for sd in source_dirs:
        discovered = discover_article_dirs(KB_ROOT, [sd])
        lines.append(f"\n## {sd} ({len(discovered)} articles)")
        for _sd, article_dir in discovered:
            md_path = article_dir / "article.md"
            if not md_path.exists():
                continue
            fm, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
            title = fm.get("title", article_dir.name)
            ct = fm.get("content_type", "")
            bv = fm.get("brainstorm_value", "")
            lines.append(f"  - [{ct}] {title} (brainstorm_value={bv})")
    if not lines:
        return "No articles found."
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 4: review_articles
# ---------------------------------------------------------------------------


@tool
def review_articles(source_dir: str = "raw", enriched_only: bool = True) -> str:
    """Show articles ready for review with detailed metadata. Displays a
    numbered list with title, content_type, brainstorm_value, and summary
    so the user can decide which status to assign.
    By default only shows enriched articles (enriched_only=True).
    Set enriched_only=False to include all articles regardless of enrichment.
    Returns the list for user to make decisions about set_article_status."""
    discovered = discover_article_dirs(KB_ROOT, [source_dir])
    if not discovered:
        return f"No articles found in {source_dir}/."

    lines: list[str] = []
    idx = 0
    for _sd, article_dir in discovered:
        md_path = article_dir / "article.md"
        if not md_path.exists():
            continue
        if enriched_only:
            source_path = article_dir / "source.json"
            if source_path.exists():
                source_data = json.loads(source_path.read_text(encoding="utf-8"))
                if not source_data.get("llm_enriched"):
                    continue
            else:
                continue
        idx += 1
        fm, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        title = fm.get("title", article_dir.name)
        ct = fm.get("content_type", "")
        bv = fm.get("brainstorm_value", "")
        summary = str(fm.get("summary", "")).strip()
        if len(summary) > 150:
            summary = summary[:150] + "..."
        lines.append(
            f"{idx}. **{title}**\n"
            f"   content_type: {ct} | brainstorm_value: {bv}\n"
            f"   summary: {summary}\n"
            f"   path: {article_dir}\n"
        )
    if not lines:
        qualifier = "enriched " if enriched_only else ""
        return f"No {qualifier}articles found in {source_dir}/."
    header = f"Enriched articles in {source_dir}/ ({idx} ready for review):\n"
    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: set_article_status
# ---------------------------------------------------------------------------


@tool
def set_article_status(article_paths: list[str], status: str, reason: str = "") -> str:
    """Batch-update the status field in article frontmatter. Accepts a list
    of article directory paths and a target status (reviewed, high_value, or rejected).
    This modifies the status: line in each article.md's YAML frontmatter.
    Articles live flat under raw/; the status field is the source of truth.
    When status is 'rejected', the article's source URL and title are recorded
    so that future re-ingestion of the same source will trigger a warning.
    Use 'reason' to note why articles are rejected (e.g. 'low research value')."""
    if status not in ("reviewed", "high_value", "rejected"):
        return f"Invalid status '{status}'. Must be 'reviewed', 'high_value', or 'rejected'."

    updated: list[str] = []
    errors: list[str] = []
    for path_str in article_paths:
        article_dir = Path(path_str).expanduser().resolve()
        md_path = article_dir / "article.md"
        if not md_path.exists():
            errors.append(f"  Not found: {md_path}")
            continue
        try:
            content = md_path.read_text(encoding="utf-8")
            new_content = re.sub(
                r"^(status:\s*)(\S+)",
                rf"\g<1>{status}",
                content,
                count=1,
                flags=re.MULTILINE,
            )
            if new_content == content and not re.search(r"^status:\s*\S+", content, flags=re.MULTILINE):
                # No status line found — insert one after the first ---
                if content.startswith("---\n"):
                    parts = content.split("---\n", 2)
                    if len(parts) >= 3:
                        parts[1] = parts[1].rstrip("\n") + f"\nstatus: {status}\n"
                        new_content = "---\n".join(parts)
            md_path.write_text(new_content, encoding="utf-8")
            title = article_dir.name
            fm, _ = parse_frontmatter(new_content)
            title = fm.get("title", title)
            updated.append(f"  {title} → {status}")

            # Record rejected sources for future ingestion warnings
            if status == "rejected":
                source_url = ""
                source_path = article_dir / "source.json"
                if source_path.exists():
                    source_data = json.loads(source_path.read_text(encoding="utf-8"))
                    source_url = source_data.get("source_url", "")
                add_rejected_source(
                    source_url=source_url,
                    title=fm.get("title", article_dir.name),
                    reason=reason or fm.get("brainstorm_value", ""),
                )
        except Exception as exc:
            errors.append(f"  Error updating {article_dir.name}: {exc}")

    lines = [f"Updated {len(updated)} article(s) to status={status}:"]
    lines.extend(updated)
    if errors:
        lines.append(f"\nErrors ({len(errors)}):")
        lines.extend(errors)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6: embed_knowledge
# ---------------------------------------------------------------------------


@tool
def embed_knowledge(force: bool = False) -> str:
    """Build or update the ChromaDB vector index from reviewed and high-value
    articles. Use force=True to re-index all articles."""
    from quant_llm_wiki.embed import (
        open_collection,
        CorruptedVectorStoreError,
        load_manifest,
        save_manifest,
        manifest_key,
        make_block_id,
        block_metadata,
        delete_article_blocks,
        write_failure_list,
        iter_wiki_blocks,
        VECTOR_STORE_DIR,
        FAILURE_LIST_PATH,
        INDEX_MANIFEST_FILENAME,
        INDEX_SCHEMA_VERSION,
    )
    from quant_llm_wiki.shared import WIKI_DIR
    from quant_llm_wiki.shared import (
        article_content_hash,
        build_blocks,
        embed_text,
        load_notes,
        DEFAULT_EMBEDDING_MODEL,
    )

    kb_root = KB_ROOT
    source_dirs = list(DEFAULT_SOURCE_DIRS)
    notes = load_notes(kb_root, source_dirs)
    if not notes:
        return "No articles found to index."

    manifest_path = VECTOR_STORE_DIR / INDEX_MANIFEST_FILENAME
    manifest = load_manifest(manifest_path)
    try:
        collection = open_collection(VECTOR_STORE_DIR)
    except CorruptedVectorStoreError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error opening vector store: {exc}"
    failures: list[dict[str, str]] = []
    success = 0
    skipped = 0

    for note in notes:
        article_key = manifest_key(kb_root, note)
        article_hash = article_content_hash(note.article_dir, INDEX_SCHEMA_VERSION)
        manifest_entry = manifest["articles"].get(article_key, {})
        if not force and manifest_entry.get("hash") == article_hash:
            skipped += 1
            continue
        blocks = build_blocks(note)
        try:
            delete_article_blocks(collection, str(note.article_dir))
            if blocks:
                ids = [make_block_id(kb_root, block, idx) for idx, block in enumerate(blocks)]
                documents = [block.text for block in blocks]
                metadatas = [block_metadata(block) for block in blocks]
                embeddings = [embed_text(text, model=DEFAULT_EMBEDDING_MODEL) for text in documents]
                collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
            manifest["articles"][article_key] = {
                "hash": article_hash,
                "block_count": len(blocks),
                "source_dir": note.source_dir,
            }
            success += 1
        except Exception as exc:
            failures.append({"article_dir": str(note.article_dir), "error": str(exc)})

    # Index wiki/ entries (concept articles + source summaries) if present
    wiki_indexed = 0
    if WIKI_DIR.exists():
        for block in iter_wiki_blocks(WIKI_DIR):
            try:
                wiki_id = make_block_id(kb_root, block, 0)
                collection.upsert(
                    ids=[wiki_id],
                    documents=[block.text],
                    metadatas=[block_metadata(block, kb_layer=block.block_type)],
                    embeddings=[embed_text(block.text, model=DEFAULT_EMBEDDING_MODEL)],
                )
                wiki_indexed += 1
            except Exception as exc:
                failures.append({"article_dir": str(block.note.article_dir), "error": str(exc)})

    save_manifest(manifest_path, manifest)
    write_failure_list(failures, FAILURE_LIST_PATH)
    wiki_note = f", {wiki_indexed} wiki entries" if wiki_indexed else ""
    return f"Embedding complete: {success} indexed, {skipped} skipped, {len(failures)} failed{wiki_note}."


# ---------------------------------------------------------------------------
# Tool 8: query_knowledge_base
# ---------------------------------------------------------------------------


@tool
def query_knowledge_base(
    query: str,
    mode: str = "ask",
    content_type: Optional[str] = None,
    market: Optional[str] = None,
    asset_type: Optional[str] = None,
    strategy_type: Optional[str] = None,
    brainstorm_value: Optional[str] = None,
    top_k: int = 8,
    retrieval: str = "hybrid",
) -> str:
    """Query the knowledge base. mode='ask' for factual Q&A, mode='brainstorm'
    for idea generation by combining insights across articles.
    Returns the LLM response with source attributions."""
    from quant_llm_wiki.query.brainstorm import (
        retrieve_blocks,
        format_context,
        build_messages,
        write_output,
        default_output_path,
        VECTOR_STORE_DIR,
    )
    from quant_llm_wiki.shared import call_zhipu_chat

    if mode not in ("ask", "brainstorm"):
        return f"Invalid mode '{mode}'. Must be 'ask' or 'brainstorm'."

    source_dirs = list(DEFAULT_SOURCE_DIRS)
    notes = load_notes(KB_ROOT, source_dirs)
    filtered = filter_notes(
        notes,
        parse_csv_arg(content_type),
        parse_csv_arg(market),
        parse_csv_arg(asset_type),
        parse_csv_arg(strategy_type),
        parse_csv_arg(brainstorm_value),
    )
    if not filtered:
        return "No candidate articles found after applying filters."

    try:
        retrieved, resolved_mode, warning = retrieve_blocks(
            filtered, query, top_k, mode, retrieval, VECTOR_STORE_DIR,
        )
    except Exception as exc:
        return f"Retrieval error: {exc}"

    if not retrieved:
        return "No relevant knowledge blocks found for the query."

    context = format_context(retrieved)
    messages = build_messages(mode, query, context)
    try:
        result = call_zhipu_chat(messages)
    except Exception as exc:
        return f"LLM error: {exc}"

    if mode == "brainstorm":
        from quant_llm_wiki.query.rethink import rethink
        result = rethink(result, retrieved, query, VECTOR_STORE_DIR)

    try:
        output_path = default_output_path(mode, query)
        write_output(output_path, query, mode, retrieved, result)
    except Exception:
        pass  # non-critical: output file write failure

    warning_text = f"\n(Warning: {warning})" if warning else ""
    return f"{result}{warning_text}"


# ---------------------------------------------------------------------------
# Tool 9: compile_wiki
# ---------------------------------------------------------------------------


@tool
def compile_wiki(mode: str = "incremental", dry_run: bool = False) -> str:
    """Compile or update the LLM-maintained wiki from reviewed/high-value articles.

    Modes:
    - 'incremental' (default): only update concepts whose sources changed.
    - 'rebuild': wipe non-seed concepts and recompile from scratch.

    Set dry_run=True to plan without writing files.
    """
    import wiki_compile
    if mode not in ("incremental", "rebuild"):
        return f"Invalid mode '{mode}'. Must be 'incremental' or 'rebuild'."
    try:
        report = wiki_compile.compile_wiki(kb_root=KB_ROOT, mode=mode, dry_run=dry_run)
    except Exception as exc:
        return f"Error during compile_wiki: {exc}"
    summary = report.summary()
    if getattr(report, "lint_summary", ""):
        summary += f"\n\nWiki health:\n{report.lint_summary}"
    if report.concepts_proposed:
        summary += (
            f"\n\n{report.concepts_proposed} low-confidence concept(s) were placed in the exception queue. "
            "They are excluded from brainstorm until the agent merges, stabilizes, or deprecates them."
        )
    return summary


# ---------------------------------------------------------------------------
# Tool 10: audit_wiki
# ---------------------------------------------------------------------------


@tool
def audit_wiki() -> str:
    """Return the wiki health report used by the agent before relying on compiled memory.

    Runs lint checks (stale sources, unsupported bullets, duplicate aliases, orphan
    concepts/sources, oversized concepts). Calls out blocking issues that should
    push brainstorm to article-only fallback.
    """
    import wiki_lint
    try:
        report = wiki_lint.lint_wiki(KB_ROOT)
    except Exception as exc:
        return f"Wiki audit failed: {exc}"
    return report.summary()


# ---------------------------------------------------------------------------
# Tool 11: list_concepts
# ---------------------------------------------------------------------------


@tool
def list_concepts(status: str = "all") -> str:
    """List wiki concepts grouped by status.

    Status filter: 'all' (default), 'stable', 'proposed', or 'deprecated'.
    Returns a markdown list of concept slugs with title and source count.
    """
    from wiki_schemas import parse_concept
    if status not in ("all", "stable", "proposed", "deprecated"):
        return f"Invalid status filter '{status}'."
    cdir = KB_ROOT / "wiki" / "concepts"
    if not cdir.exists():
        return "Wiki not initialized — run compile_wiki first."

    rows: list[str] = []
    for md in sorted(cdir.glob("*.md")):
        try:
            c = parse_concept(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status != "all" and c.status != status:
            continue
        rows.append(f"- {c.slug} — {c.title} ({c.status}) — {len(c.sources)} source(s)")
    if not rows:
        return f"No concepts match status='{status}'."
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Tool 11: set_concept_status
# ---------------------------------------------------------------------------


@tool
def set_concept_status(slug: str, status: str, reason: str = "") -> str:
    """Approve, deprecate, or delete a wiki concept by slug.

    status:
    - 'stable'     — approve a proposed concept; concept becomes part of the wiki
    - 'deprecated' — mark concept as no longer used; kept on disk for traceability
    - 'deleted'    — remove the concept file entirely

    `reason` is recorded as a short note on the change.
    """
    from wiki_schemas import parse_concept, serialize_concept
    if status not in ("stable", "deprecated", "deleted"):
        return f"Invalid status '{status}'. Must be 'stable', 'deprecated', or 'deleted'."

    path = KB_ROOT / "wiki" / "concepts" / f"{slug}.md"
    if not path.exists():
        return f"Concept not found: {slug}"

    if status == "deleted":
        path.unlink()
        return f"Deleted concept: {slug}. Reason: {reason or '(none)'}"

    try:
        concept = parse_concept(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Failed to parse concept: {exc}"
    concept.status = status
    path.write_text(serialize_concept(concept), encoding="utf-8")
    return f"Concept {slug} → {status}. Reason: {reason or '(none)'}"


# ---------------------------------------------------------------------------
# Tool 12: read_wiki
# ---------------------------------------------------------------------------


@tool
def read_wiki(target: str) -> str:
    """Read a wiki entry by name.

    target:
    - 'index' — return the wiki INDEX.md
    - <concept-slug> — return wiki/concepts/<slug>.md
    - <source-id> — return wiki/sources/<source-id>.md (the article basename)
    """
    wiki_dir = KB_ROOT / "wiki"
    if not wiki_dir.exists():
        return "Wiki not initialized — run compile_wiki first."
    if target == "index":
        idx = wiki_dir / "INDEX.md"
        return idx.read_text(encoding="utf-8") if idx.exists() else "INDEX.md not found — run compile_wiki."

    concept_path = wiki_dir / "concepts" / f"{target}.md"
    if concept_path.exists():
        return concept_path.read_text(encoding="utf-8")

    source_path = wiki_dir / "sources" / f"{target}.md"
    if source_path.exists():
        return source_path.read_text(encoding="utf-8")

    return f"Wiki entry not found: {target}"


# ---------------------------------------------------------------------------
# All tools for registration
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    ingest_article,
    enrich_articles,
    list_articles,
    review_articles,
    set_article_status,
    embed_knowledge,
    query_knowledge_base,
    compile_wiki,
    audit_wiki,
    list_concepts,
    set_concept_status,
    read_wiki,
]
