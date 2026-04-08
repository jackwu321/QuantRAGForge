from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import chromadb
except ImportError:
    chromadb = None

from kb_shared import (
    ROOT,
    KnowledgeBlock,
    call_llm_chat,
    check_vector_store_health,
    embed_text,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOVELTY_THRESHOLD = 0.75
NOVELTY_TOP_K = 5
TRACEABILITY_WEIGHT = 0.30
COHERENCE_WEIGHT = 0.35
ACTIONABILITY_WEIGHT = 0.35
DEFAULT_SCORE_ON_FAILURE = 0.5
VECTOR_STORE_DIR = ROOT / "vector_store"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BrainstormIdea:
    title: str
    inspired_by: str
    core_logic: str
    what_is_new: str
    why_it_might_work: str
    what_could_break: str
    possible_variants: str
    raw_text: str


@dataclass
class NoveltyResult:
    is_novel: bool
    top_match_title: str = ""
    top_match_path: str = ""
    top_match_score: float = 0.0
    all_matches: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class QualityScore:
    traceability: float
    coherence: float
    actionability: float
    composite: float
    coherence_reasoning: str = ""
    actionability_reasoning: str = ""


# ---------------------------------------------------------------------------
# Idea parsing
# ---------------------------------------------------------------------------

# English format: plain "Idea Title\n<title>" or markdown "### Idea Title\n<title>"
_IDEA_SPLIT_EN = re.compile(r"(?=^(?:#{2,3}\s+|\*{0,2})Idea\s+Title)", re.MULTILINE)

# Field extraction: handles both bold (**Field**) and plain (Field) headings
def _en_field(label: str) -> str:
    """Build a regex that matches both **Label** and plain Label on its own line."""
    return rf"(?:^|\n)(?:\*\*)?{label}(?:\*\*)?\s*\n([\s\S]+?)(?=\n(?:\*\*)?(?:Idea\s+Title|Inspired\s+By|Core\s+Combination|What\s+Is\s+New|Why\s+It\s+Might|What\s+Could\s+Break|Possible\s+Variants)|\n\*{3,}|\n---|\Z)"

_FIELD_PATTERNS_EN: list[tuple[str, str]] = [
    ("title", r"(?:#{2,3}\s+|\*{0,2})Idea\s+Title\s*(?:\*{0,2})\s*\n(.+?)(?:\n|$)"),
    ("inspired_by", _en_field(r"Inspired\s+By")),
    ("core_logic", _en_field(r"Core\s+Combination\s+Logic")),
    ("what_is_new", _en_field(r"What\s+Is\s+New")),
    ("why_it_might_work", _en_field(r"Why\s+It\s+Might\s+Make\s+Sense")),
    ("what_could_break", _en_field(r"What\s+Could\s+Break")),
    ("possible_variants", _en_field(r"Possible\s+Variants")),
]

# Chinese format: "## 💡 策略一：<title>" or "## 💡 创新策略一：<title>" etc.
_IDEA_SPLIT_CN = re.compile(
    r"(?=^#{2,3}\s*(?:💡\s*)?\S*(?:策略|想法|Idea)\s*[一二三四五六七八九十\d]+[：:])",
    re.MULTILINE,
)

_FIELD_PATTERNS_CN: list[tuple[str, str]] = [
    ("title", r"^#{2,3}\s*(?:💡\s*)?\S*(?:策略|想法|Idea)\s*[一二三四五六七八九十\d]+[：:]\s*(.+?)(?:\n|$)"),
    ("inspired_by", r"\*\*(?:灵感来源|来源|Inspired\s*By)[：:]*\*\*[：:\s]*\n?([\s\S]+?)(?=\n\*\*|$)"),
    ("core_logic", r"\*\*(?:核心逻辑|组合逻辑|Core\s*Logic)[：:]*\*\*[：:\s]*\n?([\s\S]+?)(?=\n\*\*|\n---|\n##|$)"),
    ("what_is_new", r"\*\*(?:创新点|新意|What\s*Is\s*New)[：:]*\*\*[：:\s]*\n?([\s\S]+?)(?=\n\*\*|\n---|\n##|$)"),
    ("why_it_might_work", r"\*\*(?:可行性|为什么可行|Why)[：:]*\*\*[：:\s]*\n?([\s\S]+?)(?=\n\*\*|\n---|\n##|$)"),
    ("what_could_break", r"\*\*(?:潜在风险|风险点|风险|What\s*Could\s*Break)[：:]*\*\*[：:\s]*\n?([\s\S]+?)(?=\n\*\*|\n---|\n##|$)"),
    ("possible_variants", r"\*\*(?:变体|可能的变体|Possible\s*Variants)[：:]*\*\*[：:\s]*\n?([\s\S]+?)$"),
]


def _try_parse_with(
    llm_output: str,
    split_re: re.Pattern,
    field_patterns: list[tuple[str, str]],
) -> list[BrainstormIdea]:
    """Attempt to parse ideas using a given split pattern and field patterns."""
    chunks = split_re.split(llm_output.strip())
    chunks = [c for c in chunks if c.strip()]
    ideas: list[BrainstormIdea] = []
    for chunk in chunks:
        fields: dict[str, str] = {}
        for name, pattern in field_patterns:
            match = re.search(pattern, chunk, re.MULTILINE)
            fields[name] = match.group(1).strip() if match else ""
        if not fields.get("title"):
            continue
        ideas.append(
            BrainstormIdea(
                title=fields["title"],
                inspired_by=fields["inspired_by"],
                core_logic=fields["core_logic"],
                what_is_new=fields["what_is_new"],
                why_it_might_work=fields["why_it_might_work"],
                what_could_break=fields["what_could_break"],
                possible_variants=fields["possible_variants"],
                raw_text=chunk.strip(),
            )
        )
    return ideas


def parse_ideas(llm_output: str) -> list[BrainstormIdea]:
    """Parse brainstorm LLM output into a list of BrainstormIdea objects.

    Tries the English structured format first, then falls back to Chinese format.
    """
    # Try English format first
    ideas = _try_parse_with(llm_output, _IDEA_SPLIT_EN, _FIELD_PATTERNS_EN)
    if ideas:
        return ideas
    # Fall back to Chinese format
    return _try_parse_with(llm_output, _IDEA_SPLIT_CN, _FIELD_PATTERNS_CN)


# ---------------------------------------------------------------------------
# Novelty check
# ---------------------------------------------------------------------------

def _open_rethink_collection(vector_store_dir: Path | None = None):
    """Open the ChromaDB knowledge_blocks collection for novelty queries."""
    if chromadb is None:
        raise RuntimeError("chromadb is required for novelty checking")
    store_dir = vector_store_dir or VECTOR_STORE_DIR
    if not store_dir.exists():
        raise RuntimeError(f"vector store directory not found: {store_dir}")
    if not check_vector_store_health(store_dir):
        raise RuntimeError(
            "Vector store was corrupted and has been cleaned up. "
            "Please run embed_knowledge to rebuild the index."
        )
    client = chromadb.PersistentClient(path=str(store_dir))
    return client.get_collection("knowledge_blocks")


def _idea_fingerprint(idea: BrainstormIdea) -> str:
    """Combine core_logic and what_is_new as the novelty fingerprint."""
    return f"{idea.core_logic}\n{idea.what_is_new}".strip()


def check_novelty(
    ideas: list[BrainstormIdea],
    vector_store_dir: Path | None = None,
) -> list[NoveltyResult]:
    """Check each idea for novelty against the existing vector store."""
    try:
        collection = _open_rethink_collection(vector_store_dir)
    except Exception:
        return [NoveltyResult(is_novel=True) for _ in ideas]

    try:
        total = int(collection.count())
    except Exception:
        total = -1
    if total <= 0:
        return [NoveltyResult(is_novel=True) for _ in ideas]

    results: list[NoveltyResult] = []
    for idea in ideas:
        fingerprint = _idea_fingerprint(idea)
        if not fingerprint:
            results.append(NoveltyResult(is_novel=True))
            continue

        try:
            query_embedding = embed_text(fingerprint)
            n_results = min(NOVELTY_TOP_K, total)
            query_result = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            results.append(NoveltyResult(is_novel=True))
            continue

        ids = query_result.get("ids", [[]])[0]
        documents = query_result.get("documents", [[]])[0]
        metadatas = query_result.get("metadatas", [[]])[0]
        distances = query_result.get("distances", [[]])[0]

        matches: list[dict[str, Any]] = []
        for _doc_id, _text, meta, dist in zip(ids, documents, metadatas, distances):
            score = max(0.0, 1.0 - float(dist))
            matches.append({
                "title": str(meta.get("article_dir", "")).split("/")[-1],
                "path": str(meta.get("article_dir", "")),
                "score": round(score, 3),
            })

        matches.sort(key=lambda m: m["score"], reverse=True)
        top = matches[0] if matches else None
        is_novel = top is None or top["score"] < NOVELTY_THRESHOLD

        results.append(
            NoveltyResult(
                is_novel=is_novel,
                top_match_title=top["title"] if top and not is_novel else "",
                top_match_path=top["path"] if top and not is_novel else "",
                top_match_score=top["score"] if top and not is_novel else 0.0,
                all_matches=matches,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Quality scoring — traceability (heuristic)
# ---------------------------------------------------------------------------

def score_traceability(idea: BrainstormIdea, retrieved_blocks: list[KnowledgeBlock]) -> float:
    """Score how well an idea traces back to its source articles.

    - inspired_by non-empty: +0.4
    - cited sources found in retrieved blocks: +0.4
    - core_logic references multiple sources: +0.2
    """
    score = 0.0

    # Check inspired_by is non-empty
    if idea.inspired_by.strip():
        score += 0.4

    # Check if cited sources exist in retrieved blocks
    source_titles = {block.note.title for block in retrieved_blocks}
    cited_found = sum(1 for title in source_titles if title in idea.inspired_by)
    if cited_found > 0:
        score += 0.4

    # Check if core_logic references multiple sources
    multi_ref_count = sum(1 for title in source_titles if title in idea.core_logic)
    if multi_ref_count >= 2:
        score += 0.2

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Quality scoring — coherence & actionability (LLM-as-judge)
# ---------------------------------------------------------------------------

RETHINK_JUDGE_SYSTEM_PROMPT = """你是量化投研想法质量评审员。
对每个想法打分（0到1），评估两个维度：
- coherence（连贯性）：组合这些来源的逻辑是否自洽？有无矛盾？
- actionability（可操作性）：这个想法是否足够具体，可以设计后续实验或回测？还是只是泛泛而谈？

返回严格JSON数组，每个元素包含：
{"idea_index": 0, "coherence": 0.8, "actionability": 0.7, "coherence_reasoning": "简要说明", "actionability_reasoning": "简要说明"}

只返回JSON，不要markdown代码块。"""


def _build_judge_prompt(ideas: list[BrainstormIdea]) -> str:
    parts: list[str] = []
    for i, idea in enumerate(ideas):
        parts.append(
            f"--- Idea {i} ---\n"
            f"Title: {idea.title}\n"
            f"Inspired By: {idea.inspired_by}\n"
            f"Core Logic: {idea.core_logic}\n"
            f"What Is New: {idea.what_is_new}\n"
            f"Why It Might Work: {idea.why_it_might_work}\n"
            f"What Could Break: {idea.what_could_break}\n"
        )
    return "\n".join(parts)


def _parse_judge_response(raw: str) -> list[dict[str, Any]]:
    """Parse JSON from LLM response, handling optional markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def _default_scores(count: int) -> list[dict[str, Any]]:
    return [
        {
            "idea_index": i,
            "coherence": DEFAULT_SCORE_ON_FAILURE,
            "actionability": DEFAULT_SCORE_ON_FAILURE,
            "coherence_reasoning": "evaluation unavailable",
            "actionability_reasoning": "evaluation unavailable",
        }
        for i in range(count)
    ]


def score_coherence_actionability(ideas: list[BrainstormIdea]) -> list[dict[str, Any]]:
    """Score ideas on coherence and actionability via a single LLM call."""
    if not ideas:
        return []
    try:
        messages = [
            {"role": "system", "content": RETHINK_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_judge_prompt(ideas)},
        ]
        raw = call_llm_chat(messages, temperature=0.1)
        parsed = _parse_judge_response(raw)
        if not isinstance(parsed, list) or len(parsed) != len(ideas):
            return _default_scores(len(ideas))
        # Normalize scores to 0-1 range
        for entry in parsed:
            entry["coherence"] = max(0.0, min(1.0, float(entry.get("coherence", DEFAULT_SCORE_ON_FAILURE))))
            entry["actionability"] = max(0.0, min(1.0, float(entry.get("actionability", DEFAULT_SCORE_ON_FAILURE))))
            entry.setdefault("coherence_reasoning", "")
            entry.setdefault("actionability_reasoning", "")
        return parsed
    except Exception:
        return _default_scores(len(ideas))


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def _compute_composite(traceability: float, coherence: float, actionability: float) -> float:
    return round(
        TRACEABILITY_WEIGHT * traceability
        + COHERENCE_WEIGHT * coherence
        + ACTIONABILITY_WEIGHT * actionability,
        2,
    )


def build_rethink_report(
    ideas: list[BrainstormIdea],
    novelty_results: list[NoveltyResult],
    quality_scores: list[QualityScore],
) -> str:
    """Build the Rethink Report markdown section."""
    if not ideas:
        return ""

    lines: list[str] = ["## Rethink Report", ""]
    for i, (idea, novelty, quality) in enumerate(zip(ideas, novelty_results, quality_scores), start=1):
        lines.append(f"### Idea {i}: {idea.title}")
        lines.append(
            f"- **Quality Score**: {quality.composite:.2f} "
            f"(Traceability: {quality.traceability:.1f} | "
            f"Coherence: {quality.coherence:.1f} | "
            f"Actionability: {quality.actionability:.1f})"
        )
        if novelty.is_novel:
            lines.append("- **Novelty**: Novel — no close matches found")
        else:
            lines.append(
                f"- **Novelty**: Similar to existing — "
                f"\"{novelty.top_match_title}\" ({novelty.top_match_score:.2f}) "
                f"in {novelty.top_match_path}"
            )
        if quality.coherence_reasoning:
            lines.append(f"- **Coherence Note**: {quality.coherence_reasoning}")
        if quality.actionability_reasoning:
            lines.append(f"- **Actionability Note**: {quality.actionability_reasoning}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def rethink(
    llm_output: str,
    retrieved_blocks: list[KnowledgeBlock],
    query: str,
    vector_store_dir: Path | None = None,
) -> str:
    """Run the rethink layer on brainstorm output.

    Returns the original output with an appended Rethink Report section.
    If parsing fails or there are no ideas, returns the original output unchanged.
    """
    if not llm_output.strip():
        return llm_output

    ideas = parse_ideas(llm_output)
    if not ideas:
        return llm_output

    # Novelty check
    novelty_results = check_novelty(ideas, vector_store_dir)

    # Traceability scoring (heuristic)
    traceability_scores = [score_traceability(idea, retrieved_blocks) for idea in ideas]

    # Coherence + actionability scoring (LLM call)
    ca_scores = score_coherence_actionability(ideas)

    # Assemble quality scores
    quality_scores: list[QualityScore] = []
    for i, idea in enumerate(ideas):
        t = traceability_scores[i]
        ca = ca_scores[i] if i < len(ca_scores) else {
            "coherence": DEFAULT_SCORE_ON_FAILURE,
            "actionability": DEFAULT_SCORE_ON_FAILURE,
            "coherence_reasoning": "evaluation unavailable",
            "actionability_reasoning": "evaluation unavailable",
        }
        c = ca["coherence"]
        a = ca["actionability"]
        quality_scores.append(
            QualityScore(
                traceability=round(t, 2),
                coherence=round(c, 2),
                actionability=round(a, 2),
                composite=_compute_composite(t, c, a),
                coherence_reasoning=ca.get("coherence_reasoning", ""),
                actionability_reasoning=ca.get("actionability_reasoning", ""),
            )
        )

    report = build_rethink_report(ideas, novelty_results, quality_scores)
    if not report:
        return llm_output

    return llm_output.rstrip() + "\n\n" + report
