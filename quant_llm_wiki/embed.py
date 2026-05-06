from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import chromadb
except ImportError:  # pragma: no cover - runtime dependency
    chromadb = None

from quant_llm_wiki.shared import (
    ROOT,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_SOURCE_DIRS,
    KnowledgeBlock,
    article_content_hash,
    build_blocks,
    check_vector_store_health,
    embed_text,
    load_notes,
    parse_csv_arg,
)


VECTOR_STORE_DIR = ROOT / "vector_store"
FAILURE_LIST_PATH = ROOT / "sources" / "processed" / "embed_failures.txt"
INDEX_MANIFEST_FILENAME = "index_manifest.json"
INDEX_SCHEMA_VERSION = "v1"
COLLECTION_NAME = "knowledge_blocks"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or update the ChromaDB vector index for the knowledge base.")
    parser.add_argument("--kb-root", default=str(ROOT), help="Knowledge base root.")
    parser.add_argument(
        "--source-dir",
        default="reviewed,high-value",
        help="Comma-separated status filters; articles live flat under raw/.",
    )
    parser.add_argument("--force", action="store_true", help="Re-index all articles even if already indexed.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be indexed without writing.")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help="Zhipu embedding model name.")
    parser.add_argument("--vector-store-dir", default=str(VECTOR_STORE_DIR), help="Directory for the persistent ChromaDB store.")
    return parser.parse_args()


def require_chromadb() -> None:
    if chromadb is None:
        raise RuntimeError("chromadb is required. Install with: pip install chromadb")


class CorruptedVectorStoreError(RuntimeError):
    """Raised when the ChromaDB store is corrupted and has been cleaned up."""


# Module-level flag: once Chroma's Rust bindings are poisoned in this process,
# no further open attempts can succeed until restart.
_chroma_poisoned = False


def open_collection(vector_store_dir: Path):
    """Open or create the ChromaDB collection.

    If the SQLite store is corrupted (e.g. from an interrupted run),
    deletes the corrupt files and raises CorruptedVectorStoreError.
    Chroma's Rust bindings hold in-process state that cannot be reset,
    so the caller must restart the process and retry.
    """
    global _chroma_poisoned
    if _chroma_poisoned:
        raise CorruptedVectorStoreError(
            "ChromaDB is unavailable in this session due to a previous store corruption. "
            "Please restart the agent and retry the embed command."
        )
    require_chromadb()
    vector_store_dir.mkdir(parents=True, exist_ok=True)
    if not check_vector_store_health(vector_store_dir):
        print("  Corrupt vector store detected and cleaned up. Rebuilding from scratch.", flush=True)
    try:
        client = chromadb.PersistentClient(path=str(vector_store_dir))
        return client.get_or_create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    except Exception as exc:
        _chroma_poisoned = True
        # Clean up corrupt files so next process start works
        import shutil
        shutil.rmtree(str(vector_store_dir), ignore_errors=True)
        vector_store_dir.mkdir(parents=True, exist_ok=True)
        # Also clear the manifest so all articles get re-indexed on retry
        manifest_path = vector_store_dir / INDEX_MANIFEST_FILENAME
        if manifest_path.exists():
            manifest_path.unlink()
        raise CorruptedVectorStoreError(
            f"ChromaDB store was corrupted ({exc}). "
            f"Corrupt files have been removed. "
            f"Please restart the agent and retry the embed command."
        ) from exc


def manifest_key(kb_root: Path, note) -> str:
    return note.article_dir.relative_to(kb_root).as_posix()


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": INDEX_SCHEMA_VERSION, "articles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": INDEX_SCHEMA_VERSION, "articles": {}}
    if data.get("schema_version") != INDEX_SCHEMA_VERSION:
        return {"schema_version": INDEX_SCHEMA_VERSION, "articles": {}}
    if not isinstance(data.get("articles"), dict):
        data["articles"] = {}
    return data


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def make_block_id(kb_root: Path, block: KnowledgeBlock, ordinal: int) -> str:
    rel_path = block.note.article_dir.relative_to(kb_root).as_posix()
    raw = f"{rel_path}|{block.block_type}|{ordinal}|{block.text}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{rel_path.replace('/', '__')}__{block.block_type}__{ordinal}__{digest}"


def block_metadata(block: KnowledgeBlock, kb_layer: str = "article") -> dict[str, str]:
    """Build ChromaDB metadata for a block. ChromaDB requires str/int/float/bool
    scalar values, so wiki score fields are coerced to floats.
    """
    frontmatter = block.note.frontmatter
    meta: dict[str, str | float | int] = {
        "article_dir": str(block.note.article_dir),
        "source_dir": block.note.source_dir,
        "content_type": str(frontmatter.get("content_type", "")),
        "brainstorm_value": str(frontmatter.get("brainstorm_value", "")),
        "block_type": block.block_type,
        "kb_layer": kb_layer,
    }
    # Wiki-specific fields used for filter+rerank at retrieval time.
    if "status" in frontmatter:
        meta["status"] = str(frontmatter["status"])
    if "slug" in frontmatter:
        meta["slug"] = str(frontmatter["slug"])
    for k in ("confidence", "importance", "freshness"):
        if k in frontmatter:
            try:
                meta[k] = float(frontmatter[k])
            except (TypeError, ValueError):
                pass
    if "source_count" in frontmatter:
        try:
            meta["source_count"] = int(frontmatter["source_count"])
        except (TypeError, ValueError):
            pass
    return meta


def delete_article_blocks(collection, article_dir: str) -> None:
    try:
        collection.delete(where={"article_dir": article_dir})
    except Exception:
        pass


def write_failure_list(failures: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not failures:
        if path.exists():
            path.unlink()
        return
    lines = [f"{item['article_dir']}\t{item['error']}" for item in failures]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    kb_root = Path(args.kb_root).expanduser().resolve()
    vector_store_dir = Path(args.vector_store_dir).expanduser().resolve()
    source_dirs = parse_csv_arg(args.source_dir) or list(DEFAULT_SOURCE_DIRS)
    notes = load_notes(kb_root, source_dirs)
    if not notes:
        print("no article dirs found")
        return 1

    manifest_path = vector_store_dir / INDEX_MANIFEST_FILENAME
    manifest = load_manifest(manifest_path)
    collection = None if args.dry_run else open_collection(vector_store_dir)
    failures: list[dict[str, str]] = []
    success = 0
    skipped = 0

    for note in notes:
        article_key = manifest_key(kb_root, note)
        article_hash = article_content_hash(note.article_dir, INDEX_SCHEMA_VERSION)
        manifest_entry = manifest["articles"].get(article_key, {})
        if not args.force and manifest_entry.get("hash") == article_hash:
            skipped += 1
            continue

        blocks = build_blocks(note)
        if args.dry_run:
            print(f"[dry-run] {article_key}: {len(blocks)} block(s)")
            success += 1
            continue

        try:
            assert collection is not None
            delete_article_blocks(collection, str(note.article_dir))
            if blocks:
                ids = [make_block_id(kb_root, block, idx) for idx, block in enumerate(blocks)]
                documents = [block.text for block in blocks]
                metadatas = [block_metadata(block) for block in blocks]
                embeddings = [embed_text(text, model=args.embedding_model) for text in documents]
                collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
            manifest["articles"][article_key] = {
                "hash": article_hash,
                "block_count": len(blocks),
                "source_dir": note.source_dir,
            }
            success += 1
        except Exception as exc:
            failures.append({"article_dir": str(note.article_dir), "error": str(exc)})

    # Index wiki/ entries (best-effort; missing wiki dir is fine)
    wiki_dir = kb_root / "wiki"
    if wiki_dir.exists() and not args.dry_run and collection is not None:
        for block in iter_wiki_blocks(wiki_dir):
            try:
                wiki_id = make_block_id(kb_root, block, 0)
                collection.upsert(
                    ids=[wiki_id],
                    documents=[block.text],
                    metadatas=[block_metadata(block, kb_layer=block.block_type)],
                    embeddings=[embed_text(block.text)],
                )
            except Exception as exc:
                failures.append({"article_dir": str(block.note.article_dir), "error": str(exc)})

    if not args.dry_run:
        save_manifest(manifest_path, manifest)
    write_failure_list(failures, FAILURE_LIST_PATH)

    summary = {
        "total": len(notes),
        "success": success,
        "skipped": skipped,
        "failed": len(failures),
        "failure_list_path": str(FAILURE_LIST_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def iter_wiki_blocks(wiki_dir: Path):
    """Yield KnowledgeBlock objects for each wiki concept article and source summary.

    The note.frontmatter dict includes wiki-specific metadata (status, slug, plus
    confidence/importance/freshness from wiki/state.json when available) so that
    block_metadata propagates them into ChromaDB. Brainstorm retrieval can then
    filter to `where={"kb_layer": "wiki_concept", "status": "stable"}` and rerank
    using the score fields.
    """
    from quant_llm_wiki.shared import KnowledgeNote
    from wiki_schemas import parse_concept, parse_source_summary
    from wiki_state import load_wiki_state

    state = load_wiki_state(wiki_dir / "state.json")

    cdir = wiki_dir / "concepts"
    if cdir.exists():
        for md in sorted(cdir.glob("*.md")):
            try:
                concept = parse_concept(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            entry = state.concepts.get(concept.slug)
            note = KnowledgeNote(
                article_dir=md,
                source_dir="wiki_concepts",
                frontmatter={
                    "title": concept.title,
                    "content_type": concept.content_types[0] if concept.content_types else "",
                    "brainstorm_value": "high",
                    "slug": concept.slug,
                    "status": concept.status,
                    "confidence": entry.confidence if entry else 0.0,
                    "importance": entry.importance if entry else 0.0,
                    "freshness": entry.freshness if entry else 0.0,
                    "source_count": entry.source_count if entry else len(concept.sources),
                },
                body="",
            )
            text = "\n\n".join(filter(None, [
                concept.synthesis,
                concept.definition,
                "\n".join(concept.key_idea_blocks),
                "\n".join(concept.variants),
                "\n".join(concept.common_combinations),
                "\n".join(concept.transfer_targets),
                "\n".join(concept.failure_modes),
            ]))
            if text.strip():
                yield KnowledgeBlock(note=note, block_type="wiki_concept", text=text, score=0.0)

    sdir = wiki_dir / "sources"
    if sdir.exists():
        for md in sorted(sdir.glob("*.md")):
            try:
                summary = parse_source_summary(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            note = KnowledgeNote(
                article_dir=md,
                source_dir="wiki_sources",
                frontmatter={
                    "title": summary.title,
                    "content_type": summary.content_type,
                    "brainstorm_value": summary.brainstorm_value,
                    "status": "stable",  # source summaries are mechanical, always usable
                },
                body="",
            )
            text = " · ".join(filter(None, [summary.takeaway] + summary.top_idea_blocks))
            if text.strip():
                yield KnowledgeBlock(note=note, block_type="wiki_source", text=text, score=0.0)


if __name__ == "__main__":
    raise SystemExit(main())

