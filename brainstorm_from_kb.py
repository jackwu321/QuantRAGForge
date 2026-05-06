from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import chromadb
except ImportError:  # pragma: no cover - runtime dependency
    chromadb = None

from quant_llm_wiki.shared import (
    ROOT,
    DEFAULT_SOURCE_DIRS,
    KnowledgeBlock,
    KnowledgeNote,
    build_blocks,
    call_zhipu_chat,
    check_vector_store_health,
    filter_notes,
    get_llm_config,
    load_notes,
    parse_csv_arg,
    parse_frontmatter,
    parse_frontmatter_value,
    require_requests,
    embed_text,
)
from rethink_layer import rethink
from wiki_schemas import parse_concept
from wiki_state import (
    concept_memory_score,
    load_wiki_state,
)


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "brainstorms"
VECTOR_STORE_DIR = ROOT / "vector_store"
WIKI_DIR = ROOT / "wiki"
WIKI_STATE_PATH = WIKI_DIR / "state.json"
SCHEMA_DIR = ROOT / "schema"
DEFAULT_TOP_K = 8
DEFAULT_RETRIEVAL_MODE = "hybrid"
DEFAULT_RETRIEVAL_FETCH_MULTIPLIER = 3
RRF_K = 60
MAX_BLOCKS_PER_NOTE_BRAINSTORM = 3
PREFERRED_BLOCK_TYPE_BONUS = {
    "idea_blocks": 0.04,
    "combination_hooks": 0.03,
    "transfer_targets": 0.03,
    "failure_modes": 0.02,
}

ASK_SYSTEM_PROMPT = """你是量化投研知识库问答助手。
你只能基于给定知识库上下文回答，不要编造未提供的回测结果、市场结论或论文结论。
输出简洁、可追溯，优先说明答案依据了哪些来源。"""

BRAINSTORM_SYSTEM_PROMPT = """你是量化投研知识库的脑暴助手。
你的目标是基于给定上下文组合出新的研究想法，而不是证明它们已有效。
必须遵守：
- 不编造不存在的回测结果
- 优先组合互补逻辑
- 明确指出每个想法来自哪些来源
- 输出使用以下结构：
Idea Title
Inspired By
Core Combination Logic
What Is New
Why It Might Make Sense
What Could Break
Possible Variants"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read the knowledge base and generate answers or brainstorm ideas.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--query", required=True, help="Question or brainstorm goal.")
    common.add_argument("--kb-root", default=str(ROOT), help="Knowledge base root directory.")
    common.add_argument("--wiki-dir", help="Wiki directory, default <kb-root>/wiki.")
    common.add_argument("--schema-dir", help="Schema directory, default <kb-root>/schema.")
    common.add_argument("--vector-store-dir", help="Vector store directory, default <kb-root>/vector_store.")
    common.add_argument(
        "--source-dir",
        default="reviewed,high-value",
        help="Comma-separated article source directories under articles/, default reviewed,high-value.",
    )
    common.add_argument("--content-type", help="Filter by comma-separated content_type values.")
    common.add_argument("--market", help="Filter by comma-separated market values.")
    common.add_argument("--asset-type", help="Filter by comma-separated asset_type values.")
    common.add_argument("--strategy-type", help="Filter by comma-separated strategy_type values.")
    common.add_argument("--brainstorm-value", help="Filter by comma-separated brainstorm_value values.")
    common.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Maximum number of retrieved blocks.")
    common.add_argument(
        "--retrieval",
        choices=["keyword", "vector", "hybrid"],
        default=DEFAULT_RETRIEVAL_MODE,
        help="Retrieval mode: keyword, vector, or hybrid.",
    )
    common.add_argument("--output-file", help="Optional explicit output file path.")
    common.add_argument("--dry-run", action="store_true", help="Print retrieved context without calling the model.")

    subparsers.add_parser("ask", parents=[common], help="Answer a question from the knowledge base.")
    subparsers.add_parser("brainstorm", parents=[common], help="Generate brainstorm ideas from the knowledge base.")
    return parser.parse_args()


def apply_filters(notes: list[KnowledgeNote], args: argparse.Namespace) -> list[KnowledgeNote]:
    return filter_notes(
        notes,
        parse_csv_arg(args.content_type),
        parse_csv_arg(args.market),
        parse_csv_arg(args.asset_type),
        parse_csv_arg(args.strategy_type),
        parse_csv_arg(args.brainstorm_value),
    )


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    ascii_tokens = re.findall(r"[a-z0-9_]+", lowered)
    cjk_sequences = re.findall(r"[\u4e00-\u9fff]+", lowered)
    cjk_tokens: list[str] = []
    for seq in cjk_sequences:
        if len(seq) == 1:
            cjk_tokens.append(seq)
            continue
        cjk_tokens.extend(seq[i : i + 2] for i in range(len(seq) - 1))
    return set(ascii_tokens + cjk_tokens)


def score_block(query: str, block: KnowledgeBlock) -> float:
    query_tokens = tokenize(query)
    block_tokens = tokenize(block.text)
    if not query_tokens or not block_tokens:
        return 0.0
    overlap = len(query_tokens & block_tokens)
    if overlap == 0:
        return 0.0
    score = overlap / max(1, len(query_tokens))
    if block.block_type == "idea_blocks":
        score += 0.25
    elif block.block_type in {"combination_hooks", "transfer_targets", "failure_modes"}:
        score += 0.2
    elif block.block_type in {"summary", "core_hypothesis"}:
        score += 0.15
    return score


def _apply_diversity_limit(blocks: list[KnowledgeBlock], limit: int, command: str) -> list[KnowledgeBlock]:
    if command != "brainstorm":
        return blocks[:limit]
    selected: list[KnowledgeBlock] = []
    note_counts: dict[str, int] = {}
    for block in blocks:
        note_key = str(block.note.article_dir)
        if note_counts.get(note_key, 0) >= MAX_BLOCKS_PER_NOTE_BRAINSTORM:
            continue
        selected.append(block)
        note_counts[note_key] = note_counts.get(note_key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _keyword_candidates(notes: list[KnowledgeNote], query: str, candidate_k: int, command: str) -> list[KnowledgeBlock]:
    scored: list[KnowledgeBlock] = []
    for note in notes:
        for block in build_blocks(note):
            block.score = score_block(query, block)
            if block.score > 0:
                scored.append(block)
    scored.sort(key=lambda item: (item.score, PREFERRED_BLOCK_TYPE_BONUS.get(item.block_type, 0.0)), reverse=True)
    return _apply_diversity_limit(scored, candidate_k, command)


def _open_vector_collection(vector_store_dir: Path):
    if chromadb is None:
        raise RuntimeError("chromadb is required for vector or hybrid retrieval. Install with: pip install chromadb")
    if not vector_store_dir.exists():
        raise RuntimeError(f"vector store directory not found: {vector_store_dir}")
    if not check_vector_store_health(vector_store_dir):
        raise RuntimeError(
            "Vector store was corrupted and has been cleaned up. "
            "Please run embed_knowledge to rebuild the index."
        )
    client = chromadb.PersistentClient(path=str(vector_store_dir))
    return client.get_collection("knowledge_blocks")


def _vector_retrieve(
    notes: list[KnowledgeNote],
    query: str,
    candidate_k: int,
    command: str,
    vector_store_dir: Path,
) -> list[KnowledgeBlock]:
    collection = _open_vector_collection(vector_store_dir)
    total = collection.count()
    if total <= 0:
        return []

    allowed_dirs = {str(note.article_dir): note for note in notes}
    query_embedding = embed_text(query)
    n_results = min(max(candidate_k * DEFAULT_RETRIEVAL_FETCH_MULTIPLIER, candidate_k), total)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    blocks: list[KnowledgeBlock] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for _doc_id, text, meta, dist in zip(ids, documents, metadatas, distances):
        article_dir_str = str(meta.get("article_dir", "")).strip()
        note = allowed_dirs.get(article_dir_str)
        if note is None:
            continue
        block = KnowledgeBlock(
            note=note,
            block_type=str(meta.get("block_type", "unknown")),
            text=str(text).strip(),
            score=max(0.0, 1.0 - float(dist)),
        )
        blocks.append(block)

    blocks.sort(key=lambda item: (item.score, PREFERRED_BLOCK_TYPE_BONUS.get(item.block_type, 0.0)), reverse=True)
    return _apply_diversity_limit(blocks, candidate_k, command)


def _rrf_fusion(keyword_blocks: list[KnowledgeBlock], vector_blocks: list[KnowledgeBlock], top_k: int) -> list[KnowledgeBlock]:
    def block_key(block: KnowledgeBlock) -> tuple[str, str, str]:
        return (str(block.note.article_dir), block.block_type, block.text)

    rrf_scores: dict[tuple[str, str, str], float] = {}
    block_objects: dict[tuple[str, str, str], KnowledgeBlock] = {}

    for rank, block in enumerate(keyword_blocks, start=1):
        key = block_key(block)
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (rank + RRF_K)
        block_objects[key] = block

    for rank, block in enumerate(vector_blocks, start=1):
        key = block_key(block)
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (rank + RRF_K)
        block_objects[key] = block

    fused = sorted(
        rrf_scores,
        key=lambda key: (rrf_scores[key] + PREFERRED_BLOCK_TYPE_BONUS.get(block_objects[key].block_type, 0.0)),
        reverse=True,
    )

    results: list[KnowledgeBlock] = []
    for key in fused[:top_k]:
        block = block_objects[key]
        block.score = rrf_scores[key]
        results.append(block)
    return results


# ---------------------------------------------------------------------------
# Wiki-concept retrieval (Chroma-filtered, state-score reranked)
# ---------------------------------------------------------------------------

DEFAULT_CONCEPT_TOP_K = 3
CONCEPT_FETCH_MULTIPLIER = 4  # over-fetch from Chroma so the rerank has options
RERANK_W_SIM = 0.50
RERANK_W_MEMORY = 0.50  # the rest is composed inside concept_memory_score


def _build_concept_body(c) -> str:
    """Compact memory block for a concept: synthesis + structured bullets."""
    parts = list(filter(None, [
        c.synthesis,
        c.definition,
    ]))
    if c.key_idea_blocks:
        parts.append("Key Idea Blocks:\n" + "\n".join(f"- {b}" for b in c.key_idea_blocks))
    if c.common_combinations:
        parts.append("Combinations: " + "; ".join(c.common_combinations))
    if c.transfer_targets:
        parts.append("Transfer Targets: " + "; ".join(c.transfer_targets))
    if c.failure_modes:
        parts.append("Failure Modes: " + "; ".join(c.failure_modes))
    return "\n\n".join(parts)


def _retrieve_concepts_via_chroma(
    query: str,
    top_k: int,
    vector_store_dir: Path,
    wiki_dir: Path,
) -> list[dict] | None:
    """Vector-search Chroma for wiki concepts. Returns None if Chroma unavailable.

    Filters to `kb_layer=wiki_concept AND status=stable`. Reranks using
    state.json memory score (confidence + importance + freshness − conflicts).
    """
    if chromadb is None or not vector_store_dir.exists():
        return None
    try:
        if not check_vector_store_health(vector_store_dir):
            return None
        client = chromadb.PersistentClient(path=str(vector_store_dir))
        collection = client.get_collection("knowledge_blocks")
    except Exception:
        return None

    if collection.count() <= 0:
        return None

    try:
        query_embedding = embed_text(query)
    except Exception:
        return None

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(top_k * CONCEPT_FETCH_MULTIPLIER, top_k),
            where={"$and": [
                {"kb_layer": {"$eq": "wiki_concept"}},
                {"status": {"$eq": "stable"}},
            ]},
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return None

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    if not metas:
        return None

    state = load_wiki_state(wiki_dir / "state.json")
    scored: list[tuple[float, dict, str]] = []
    for text, meta, dist in zip(docs, metas, dists):
        slug = str(meta.get("slug", "")).strip()
        if not slug:
            continue
        sim = max(0.0, 1.0 - float(dist))
        entry = state.concepts.get(slug)
        if entry is None:
            mem_score = 0.0
            conflict_count = 0
        else:
            mem_score = concept_memory_score(
                confidence=entry.confidence,
                importance=entry.importance,
                freshness=entry.freshness,
                source_count=entry.source_count,
                conflict_count=len(entry.conflicts),
            )
            conflict_count = len(entry.conflicts)
        final = RERANK_W_SIM * sim + RERANK_W_MEMORY * mem_score
        scored.append((final, meta, text))

    scored.sort(key=lambda kv: kv[0], reverse=True)

    # Read full concept articles from disk to surface structured bullets,
    # not just the embedded body.
    out: list[dict] = []
    seen_slugs: set[str] = set()
    for _, meta, text in scored:
        slug = str(meta.get("slug", ""))
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        concept_md = wiki_dir / "concepts" / f"{slug}.md"
        if not concept_md.exists():
            continue
        try:
            c = parse_concept(concept_md.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "slug": c.slug,
            "title": c.title,
            "sources": c.sources,
            "body_text": _build_concept_body(c),
        })
        if len(out) >= top_k:
            break
    return out or None


def _retrieve_concepts_via_lexical(query: str, top_k: int, wiki_dir: Path) -> list[dict]:
    """Lexical fallback for concept retrieval. Used when Chroma is unavailable.

    Scores concepts by token overlap of query against title + aliases +
    retrieval_hints (from state.json). Plain and deterministic.
    """
    cdir = wiki_dir / "concepts"
    if not cdir.exists():
        return []
    candidates = []
    for md in cdir.glob("*.md"):
        try:
            c = parse_concept(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        if c.status != "stable":
            continue
        candidates.append(c)
    if not candidates:
        return []

    state = load_wiki_state(wiki_dir / "state.json")
    q_tokens = tokenize(query)
    scored = []
    for c in candidates:
        entry = state.concepts.get(c.slug)
        hints = list(entry.retrieval_hints) if entry else (list(c.aliases) + [c.title])
        score_text = " ".join([c.title] + hints + [c.definition[:200]])
        c_tokens = tokenize(score_text)
        overlap = len(q_tokens & c_tokens)
        if overlap == 0:
            continue
        if entry is not None:
            mem = concept_memory_score(
                confidence=entry.confidence,
                importance=entry.importance,
                freshness=entry.freshness,
                source_count=entry.source_count,
                conflict_count=len(entry.conflicts),
            )
        else:
            mem = 0.0
        scored.append((overlap + 2.0 * mem, c))
    scored.sort(key=lambda kv: kv[0], reverse=True)

    return [
        {
            "slug": c.slug,
            "title": c.title,
            "sources": c.sources,
            "body_text": _build_concept_body(c),
        }
        for _, c in scored[:top_k]
    ]


def _retrieve_concept_articles(
    query: str,
    top_k: int = DEFAULT_CONCEPT_TOP_K,
    vector_store_dir: Path | None = None,
    wiki_dir: Path | None = None,
) -> list[dict]:
    """Retrieve top-K stable wiki concepts.

    Preferred: Chroma vector search filtered to `kb_layer=wiki_concept`,
    reranked by `wiki/state.json` memory score
    (vector_sim + confidence + importance + freshness - conflicts).
    Fallback: lexical token overlap on title/aliases/retrieval_hints when
    Chroma is unavailable, the index is empty, or the query has no hits.
    """
    resolved_wiki_dir = wiki_dir or WIKI_DIR
    if not (resolved_wiki_dir / "concepts").exists():
        return []
    store = vector_store_dir or VECTOR_STORE_DIR
    via_chroma = _retrieve_concepts_via_chroma(query, top_k, store, resolved_wiki_dir)
    if via_chroma:
        return via_chroma
    return _retrieve_concepts_via_lexical(query, top_k, resolved_wiki_dir)


def _concepts_to_blocks(
    query: str,
    top_k: int = DEFAULT_CONCEPT_TOP_K,
    vector_store_dir: Path | None = None,
    wiki_dir: Path | None = None,
) -> list[KnowledgeBlock]:
    resolved_wiki_dir = wiki_dir or WIKI_DIR
    concepts = _retrieve_concept_articles(
        query,
        top_k=top_k,
        vector_store_dir=vector_store_dir,
        wiki_dir=resolved_wiki_dir,
    )
    if not concepts:
        return []
    blocks: list[KnowledgeBlock] = []
    for c in concepts:
        note = KnowledgeNote(
            article_dir=resolved_wiki_dir / "concepts" / f"{c['slug']}.md",
            source_dir="wiki_concepts",
            frontmatter={"title": c["title"], "content_type": ""},
            body="",
        )
        blocks.append(KnowledgeBlock(
            note=note,
            block_type="wiki_concept",
            text=c["body_text"],
            score=1.0,
        ))
    return blocks


def _wiki_is_healthy_for_query(kb_root: Path) -> bool:
    """Audit the wiki — return True if brainstorm should use compiled memory."""
    try:
        from wiki_lint import lint_wiki
        return lint_wiki(kb_root).ok_for_brainstorm()
    except Exception:
        return True  # absence of lint is not a blocker; the lint itself is best-effort


def _should_use_wiki_memory(notes: list[KnowledgeNote]) -> bool:
    """Use wiki memory only for notes loaded from a concrete KB root."""
    return any(note.article_dir.is_absolute() for note in notes)


def retrieve_blocks(
    notes: list[KnowledgeNote],
    query: str,
    top_k: int,
    command: str,
    retrieval_mode: str,
    vector_store_dir: Path | None = None,
    kb_root: Path | None = None,
    wiki_dir: Path | None = None,
    schema_dir: Path | None = None,
) -> tuple[list[KnowledgeBlock], str, str | None]:
    candidate_k = max(top_k * 2, top_k)
    keyword_blocks = _keyword_candidates(notes, query, candidate_k, command)
    resolved_kb_root = kb_root or ROOT
    resolved_wiki_dir = wiki_dir or (resolved_kb_root / "wiki")
    _resolved_schema_dir = schema_dir or (resolved_kb_root / "schema")
    store_dir = vector_store_dir or (resolved_kb_root / "vector_store")

    # Wiki-first: compiled concepts are the primary memory; articles/vectors only supplement them.
    wiki_blocks: list[KnowledgeBlock] = []
    excluded_articles: set[str] = set()
    if _should_use_wiki_memory(notes) and _wiki_is_healthy_for_query(resolved_kb_root):
        wiki_blocks = _concepts_to_blocks(
            query,
            top_k=DEFAULT_CONCEPT_TOP_K,
            vector_store_dir=store_dir,
            wiki_dir=resolved_wiki_dir,
        )
        if wiki_blocks:
            for c in _retrieve_concept_articles(
                query,
                top_k=DEFAULT_CONCEPT_TOP_K,
                vector_store_dir=store_dir,
                wiki_dir=resolved_wiki_dir,
            ):
                for src_path in c["sources"]:
                    src = Path(src_path)
                    if not src.is_absolute():
                        src = resolved_kb_root / src
                    excluded_articles.add(str(src.parent))

    remaining_k = max(0, top_k - len(wiki_blocks))

    if retrieval_mode == "keyword":
        article_blocks = [
            b for b in keyword_blocks
            if str(b.note.article_dir) not in excluded_articles
        ][:remaining_k]
        return wiki_blocks + article_blocks, "keyword", None

    try:
        vector_blocks = _vector_retrieve(notes, query, candidate_k, command, store_dir)
    except Exception as exc:
        warning = f"{retrieval_mode} retrieval fell back to keyword: {exc}"
        article_blocks = [
            b for b in keyword_blocks
            if str(b.note.article_dir) not in excluded_articles
        ][:remaining_k]
        return wiki_blocks + article_blocks, "keyword", warning

    vector_blocks = [b for b in vector_blocks if str(b.note.article_dir) not in excluded_articles]

    if retrieval_mode == "vector":
        if vector_blocks:
            return wiki_blocks + vector_blocks[:remaining_k], "vector", None
        return wiki_blocks + keyword_blocks[:remaining_k], "keyword", "vector retrieval returned no results; fell back to keyword"

    if not vector_blocks:
        return wiki_blocks + keyword_blocks[:remaining_k], "keyword", \
            "hybrid retrieval fell back to keyword because vector retrieval returned no results"

    fused = _rrf_fusion(keyword_blocks, vector_blocks, remaining_k)
    if not fused:
        return wiki_blocks + keyword_blocks[:remaining_k], "keyword", \
            "hybrid retrieval fell back to keyword because fusion returned no results"
    return wiki_blocks + fused, "hybrid", None


def format_context(blocks: list[KnowledgeBlock]) -> str:
    chunks: list[str] = []
    for index, block in enumerate(blocks, start=1):
        label = "Wiki Concept" if block.block_type == "wiki_concept" else (
            "Wiki Source Summary" if block.block_type == "wiki_source" else "Article"
        )
        chunks.append(
            "\n".join(
                [
                    f"[Context {index}] [{label}]",
                    f"Title: {block.note.title}",
                    f"Path: {block.note.article_dir}",
                    f"Content Type: {block.note.frontmatter.get('content_type', '')}",
                    f"Block Type: {block.block_type}",
                    f"Content: {block.text}",
                ]
            )
        )
    return "\n\n".join(chunks)


def build_messages(command: str, query: str, context: str) -> list[dict[str, str]]:
    system_prompt = ASK_SYSTEM_PROMPT if command == "ask" else BRAINSTORM_SYSTEM_PROMPT
    user_prompt = "\n\n".join(
        [
            f"任务类型: {command}",
            f"用户问题: {query}",
            "请严格基于以下知识库上下文输出结果：",
            context,
        ]
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[\\/:*?\"<>|：？“”‘’《》【】｜]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip(" ._")
    return value[:80] or "result"


def default_output_path(command: str, query: str, output_dir: Path | None = None) -> Path:
    date_part = datetime.now().strftime("%Y-%m-%d")
    suffix = "ask" if command == "ask" else "brainstorm"
    base_dir = output_dir or DEFAULT_OUTPUT_DIR
    return base_dir / f"{date_part}_{slugify(query)}_{suffix}.md"


def write_output(path: Path, query: str, command: str, blocks: list[KnowledgeBlock], result: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    source_paths = [str(block.note.article_dir) for block in blocks]
    deduped_sources: list[str] = []
    for source in source_paths:
        if source not in deduped_sources:
            deduped_sources.append(source)
    content = "\n".join(
        [
            f"# {command.title()} Result",
            "",
            f"Query: {query}",
            "",
            "## Retrieved Sources",
            "",
            *[f"- {source}" for source in deduped_sources],
            "",
            "## Output",
            "",
            result,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    kb_root = Path(args.kb_root).expanduser().resolve()
    wiki_dir = Path(args.wiki_dir).expanduser().resolve() if args.wiki_dir else kb_root / "wiki"
    schema_dir = Path(args.schema_dir).expanduser().resolve() if args.schema_dir else kb_root / "schema"
    vector_store_dir = Path(args.vector_store_dir).expanduser().resolve() if args.vector_store_dir else kb_root / "vector_store"
    source_dirs = parse_csv_arg(args.source_dir) or list(DEFAULT_SOURCE_DIRS)
    notes = load_notes(kb_root, source_dirs)
    filtered_notes = apply_filters(notes, args)
    if not filtered_notes:
        print("no candidate notes found after applying source/status/metadata filters")
        return 1

    retrieved, resolved_mode, warning = retrieve_blocks(
        filtered_notes,
        args.query,
        args.top_k,
        args.command,
        args.retrieval,
        vector_store_dir,
        kb_root=kb_root,
        wiki_dir=wiki_dir,
        schema_dir=schema_dir,
    )
    if warning:
        print(f"warning: {warning}")
    print(f"retrieval_mode: {resolved_mode}")
    if not retrieved:
        print("no relevant knowledge blocks found for the query")
        return 1

    context = format_context(retrieved)
    if args.dry_run:
        print(context)
        return 0

    result = call_zhipu_chat(build_messages(args.command, args.query, context))
    if args.command == "brainstorm":
        result = rethink(result, retrieved, args.query, vector_store_dir)
    output_path = (
        Path(args.output_file).expanduser().resolve()
        if args.output_file
        else default_output_path(args.command, args.query, kb_root / "outputs" / "brainstorms")
    )
    saved = write_output(output_path, args.query, args.command, retrieved, result)
    print(result)
    print(f"\nsaved: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
