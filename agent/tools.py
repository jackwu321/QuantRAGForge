from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

# Ensure project root is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kb_shared import (
    ROOT as KB_ROOT,
    DEFAULT_SOURCE_DIRS,
    discover_article_dirs,
    load_notes,
    parse_frontmatter,
    filter_notes,
    parse_csv_arg,
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
    content_type: Optional[str] = None,
    force: bool = False,
) -> str:
    """Ingest articles into the knowledge base from various sources.

    Accepts ONE of the following (in priority order):
    - url: A single WeChat article URL
    - urls: Multiple URLs separated by newlines or commas
    - url_list_file: Path to a .txt file with one URL per line
    - html_file: Path to a locally saved HTML file

    Set force=True to re-ingest articles that already exist in the knowledge base.
    By default, duplicate articles are detected and skipped with a warning.

    Each article is fetched, parsed (text/images/code extracted),
    classified by content_type, and saved to articles/raw/.
    Returns a summary of successes, skips, and failures."""
    from ingest_wechat_article import (
        ingest_single_url,
        load_url_list,
        extract_article_data,
        write_article,
        fetch_html,
        detect_blocked_wechat_page,
        DuplicateArticleError,
        BatchResult,
    )

    args = argparse.Namespace(title=None, content_type=content_type, dry_run=False, force=force)

    # Single HTML file
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
            url_list = load_url_list(url_list_file)
        except Exception as exc:
            return f"Error reading URL list file {url_list_file}: {exc}"
        if not url_list:
            return f"No valid URLs found in {url_list_file}"
    elif urls:
        # Split on newlines, commas, or semicolons
        raw = urls.replace(",", "\n").replace(";", "\n").replace("，", "\n").replace("；", "\n")
        url_list = [u.strip() for u in raw.splitlines() if u.strip()]
    elif url:
        url_list = [url]
    else:
        return "Please provide one of: url, urls, url_list_file, or html_file."

    # Ingest each URL
    results: list[str] = []
    success_count = 0
    skipped_count = 0
    for i, u in enumerate(url_list, start=1):
        result: BatchResult = ingest_single_url(u, args)
        if result.skipped:
            skipped_count += 1
            results.append(f"[{i}/{len(url_list)}] SKIPPED (exists): {result.output_dir}")
        elif result.success:
            success_count += 1
            results.append(f"[{i}/{len(url_list)}] OK: {result.output_dir}")
        else:
            results.append(f"[{i}/{len(url_list)}] FAILED {u}: {result.error}")

    fail_count = len(url_list) - success_count - skipped_count
    parts = [f"{success_count} ingested"]
    if skipped_count:
        parts.append(f"{skipped_count} skipped (already exist)")
    if fail_count:
        parts.append(f"{fail_count} failed")
    summary = f"Result: {', '.join(parts)} (total {len(url_list)})"
    return summary + "\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Tool 2: enrich_articles
# ---------------------------------------------------------------------------


@tool
def enrich_articles(
    article_dir: Optional[str] = None,
    status_filter: str = "raw",
    force: bool = False,
) -> str:
    """Enrich articles with LLM-generated structured metadata (idea_blocks,
    transfer_targets, combination_hooks, failure_modes, etc.).
    Optionally specify a single article_dir, or process all articles matching
    the status_filter (default: raw)."""
    from enrich_articles_with_llm import (
        discover_article_dirs as enrich_discover,
        process_article_dir,
        ProcessResult,
    )

    args = argparse.Namespace(
        article_dir=article_dir,
        articles_root=str(KB_ROOT / "articles" / "raw"),
        status_filter=status_filter,
        force=force,
        dry_run=False,
        limit=None,
    )
    try:
        article_dirs = enrich_discover(args)
    except Exception as exc:
        return f"Error discovering articles: {exc}"

    if not article_dirs:
        return "No articles found matching the criteria."

    results: list[ProcessResult] = []
    for ad in article_dirs:
        result = process_article_dir(ad, args)
        results.append(result)

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
def review_articles(source_dir: str = "raw") -> str:
    """Show articles ready for review with detailed metadata. Displays a
    numbered list with title, content_type, brainstorm_value, and summary
    so the user can decide which status to assign.
    Returns the list for user to make decisions about set_article_status."""
    discovered = discover_article_dirs(KB_ROOT, [source_dir])
    if not discovered:
        return f"No articles found in {source_dir}/."

    lines: list[str] = [f"Articles in {source_dir}/ ({len(discovered)} total):\n"]
    for idx, (_sd, article_dir) in enumerate(discovered, start=1):
        md_path = article_dir / "article.md"
        if not md_path.exists():
            continue
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
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: set_article_status
# ---------------------------------------------------------------------------


@tool
def set_article_status(article_paths: list[str], status: str) -> str:
    """Batch-update the status field in article frontmatter. Accepts a list
    of article directory paths and a target status (reviewed or high_value).
    This modifies the status: line in each article.md's YAML frontmatter,
    preparing them for sync_articles to move to the correct directory."""
    if status not in ("reviewed", "high_value"):
        return f"Invalid status '{status}'. Must be 'reviewed' or 'high_value'."

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
        except Exception as exc:
            errors.append(f"  Error updating {article_dir.name}: {exc}")

    lines = [f"Updated {len(updated)} article(s) to status={status}:"]
    lines.extend(updated)
    if errors:
        lines.append(f"\nErrors ({len(errors)}):")
        lines.extend(errors)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6: sync_articles
# ---------------------------------------------------------------------------


@tool
def sync_articles(source_dir: Optional[str] = None) -> str:
    """Move articles from raw/ to reviewed/ or high-value/ based on their
    frontmatter status field. Run this after set_article_status."""
    from sync_articles_by_status import sync_by_status, ARTICLES_DIR, DEFAULT_SOURCE_DIR

    src = Path(source_dir).expanduser().resolve() if source_dir else DEFAULT_SOURCE_DIR
    try:
        results = sync_by_status(src, dry_run=False)
    except Exception as exc:
        return f"Error during sync: {exc}"

    moved = [r for r in results if r.moved]
    skipped = [r for r in results if not r.moved]
    lines = [f"Sync complete: {len(moved)} moved, {len(skipped)} skipped."]
    for r in moved:
        lines.append(f"  {Path(r.article_dir).name} → {r.target_dir} (status={r.status})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 7: embed_knowledge
# ---------------------------------------------------------------------------


@tool
def embed_knowledge(force: bool = False) -> str:
    """Build or update the ChromaDB vector index from reviewed and high-value
    articles. Use force=True to re-index all articles."""
    from embed_knowledge_base import (
        open_collection,
        load_manifest,
        save_manifest,
        manifest_key,
        make_block_id,
        block_metadata,
        delete_article_blocks,
        write_failure_list,
        VECTOR_STORE_DIR,
        FAILURE_LIST_PATH,
        INDEX_MANIFEST_FILENAME,
        INDEX_SCHEMA_VERSION,
    )
    from kb_shared import (
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
    collection = open_collection(VECTOR_STORE_DIR)
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

    save_manifest(manifest_path, manifest)
    write_failure_list(failures, FAILURE_LIST_PATH)
    return f"Embedding complete: {success} indexed, {skipped} skipped, {len(failures)} failed."


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
    from brainstorm_from_kb import (
        retrieve_blocks,
        format_context,
        build_messages,
        write_output,
        default_output_path,
        VECTOR_STORE_DIR,
    )
    from kb_shared import call_zhipu_chat

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
        from rethink_layer import rethink
        result = rethink(result, retrieved, query, VECTOR_STORE_DIR)

    try:
        output_path = default_output_path(mode, query)
        write_output(output_path, query, mode, retrieved, result)
    except Exception:
        pass  # non-critical: output file write failure

    warning_text = f"\n(Warning: {warning})" if warning else ""
    return f"{result}{warning_text}"


# ---------------------------------------------------------------------------
# All tools for registration
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    ingest_article,
    enrich_articles,
    list_articles,
    review_articles,
    set_article_status,
    sync_articles,
    embed_knowledge,
    query_knowledge_base,
]
