#!/usr/bin/env python3
"""Benchmark harness for v0.4.3 perf wins. See benchmarks/README.md."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Ensure the repo root (parent of scripts/) is first on sys.path so the
# source-tree quant_llm_wiki (with perf instrumentation) shadows any installed wheel.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SCALES = {
    "small":  {"articles": 20,  "concepts": 10,  "feeds": 3},
    "medium": {"articles": 100, "concepts": 40,  "feeds": 4},
    "large":  {"articles": 500, "concepts": 100, "feeds": 5},
}


def build_synthetic_kb(root: Path, n_articles: int, n_concepts: int, feeds_per_article: int) -> None:
    """Lay out a deterministic KB at `root` ready for compile_wiki."""
    # Articles must live under raw/ — compile.py's _list_articles scans raw/
    articles_root = root / "raw"
    articles_root.mkdir(parents=True, exist_ok=True)
    for i in range(n_articles):
        ad = articles_root / f"a{i:04d}"
        ad.mkdir()
        body_topic_id = i % max(n_concepts, 1)
        # Concept slugs: hyphens only (SLUG_RE = r"^[a-z0-9]+(-[a-z0-9]+)*$")
        (ad / "article.md").write_text(
            f"---\ntitle: Article {i}\ncontent_type: paper\nmain_topic: topic-{body_topic_id:04d}\n---\n"
            f"body for article {i} about topic {body_topic_id}.\n",
            encoding="utf-8",
        )

    wiki_root = root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True, exist_ok=True)
    for j in range(n_concepts):
        slug = f"topic-{j:04d}"
        (wiki_root / "concepts" / f"{slug}.md").write_text(
            f"---\ntitle: Topic {j}\nslug: {slug}\nstatus: stable\naliases: []\nrelated_concepts: []\n"
            f"sources: []\ncontent_types: [paper]\nlast_compiled: 2026-01-01\ncompile_version: 0\n"
            f"source_basenames: []\n---\nDefinition for topic {j}.\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--scale", choices=list(SCALES), default="medium")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--out", type=Path, default=Path("benchmarks"))
    p.add_argument("--label", type=str, default=None,
                   help="Free-form label embedded in the JSON record (e.g. 'v0.4.3-HEAD').")
    return p.parse_args()


def _run_trial(scale: dict) -> dict:
    """Run one compile + brainstorm pair, return parsed perf timings."""
    import io
    import unittest.mock
    from contextlib import redirect_stderr

    from quant_llm_wiki.wiki import compile as compile_mod
    from quant_llm_wiki.query import brainstorm as brainstorm_mod
    from quant_llm_wiki.shared import KnowledgeNote
    from quant_llm_wiki.wiki.compile_llm import ConceptAssignment, RecompileResult

    with tempfile.TemporaryDirectory() as tmp:
        kb_root = Path(tmp)
        build_synthetic_kb(kb_root, scale["articles"], scale["concepts"], scale["feeds"])

        # Mock LLM: assignment picks `feeds` existing concepts deterministically per article.
        def fake_assign(*, article_frontmatter, index_text, schema_text=None):
            topic = article_frontmatter.get("main_topic", "topic-0000")
            base = int(topic.split("-")[-1])
            slugs = [f"topic-{(base + k) % scale['concepts']:04d}" for k in range(scale["feeds"])]
            return ConceptAssignment(existing_concepts=slugs, proposed_new_concepts=[], error="")

        def fake_recompile(*, concept_slug, concept_title, source_articles, schema_text=None):
            return RecompileResult(
                synthesis=f"s for {concept_slug}",
                definition=f"d for {concept_slug}",
                related_concepts=[], key_idea_blocks=[], variants=[],
                common_combinations=[], transfer_targets=[],
                failure_modes=[], open_questions=[], error="",
            )

        # Mock concept retrieval: return scale["feeds"] deterministic dicts.
        # The harness owns the call counter — we observe the v0.4.2→v0.4.3
        # dedup invariant externally instead of relying on an in-code log field.
        retrieve_call_count = [0]

        def fake_retrieve_concepts(query, top_k=None, vector_store_dir=None, wiki_dir=None):
            retrieve_call_count[0] += 1
            n = min(top_k or 5, scale["concepts"])
            return [
                {
                    "slug": f"topic-{k:04d}",
                    "title": f"Topic {k}",
                    "body_text": f"body for topic {k}",
                    "sources": [],
                }
                for k in range(n)
            ]

        buf_compile = io.StringIO()
        buf_query = io.StringIO()

        with unittest.mock.patch.object(compile_mod, "assign_concepts", side_effect=fake_assign), \
             unittest.mock.patch.object(compile_mod, "recompile_concept", side_effect=fake_recompile):
            t_compile = time.perf_counter()
            with redirect_stderr(buf_compile):
                compile_mod.compile_wiki(
                    kb_root=kb_root,
                    source_dirs=("raw",),
                    mode="incremental",
                    dry_run=False,
                )
            wall_compile_ms = (time.perf_counter() - t_compile) * 1000.0

        # Brainstorm: drive retrieve_blocks with the wiki we just compiled.
        note = KnowledgeNote(
            article_dir=kb_root / "raw" / "a0000" / "article.md",
            source_dir="raw",
            frontmatter={"title": "a0", "content_type": "paper"},
            body="hello",
        )
        with unittest.mock.patch.object(
                brainstorm_mod, "_retrieve_concept_articles",
                side_effect=fake_retrieve_concepts), \
             unittest.mock.patch.object(
                brainstorm_mod, "_wiki_is_healthy_for_query", return_value=True):
            t_query = time.perf_counter()
            with redirect_stderr(buf_query):
                brainstorm_mod.retrieve_blocks(
                    [note], "any query", top_k=5,
                    command="brainstorm", retrieval_mode="keyword",
                    kb_root=kb_root,
                )
            wall_query_ms = (time.perf_counter() - t_query) * 1000.0

    rb = _parse_event(buf_query.getvalue(), "retrieve_blocks", wall_ms=wall_query_ms)
    rb["concept_retrievals_observed"] = retrieve_call_count[0]
    return {
        "compile_wiki": _parse_event(buf_compile.getvalue(), "compile_wiki",
                                     wall_ms=wall_compile_ms),
        "retrieve_blocks": rb,
        "_retrieve_concept_articles": _parse_event(buf_query.getvalue(),
                                                   "_retrieve_concept_articles",
                                                   default={"calls": 0}),
    }


def _parse_event(stderr: str, event: str, wall_ms: float | None = None, default: dict | None = None) -> dict:
    """Pull the named [qlw-perf] event from stderr; return numeric-cast fields."""
    import re
    line_re = re.compile(rf"^\[qlw-perf\] {re.escape(event)}: (.+)$")
    out = {}
    calls = 0
    for line in stderr.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        calls += 1
        for kv in m.group(1).split():
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            try:
                out[k] = float(v) if "." in v else int(v)
            except ValueError:
                out[k] = v
    if calls == 0 and default is not None:
        return default
    out["calls"] = calls
    if wall_ms is not None:
        out["wall_ms"] = wall_ms
    return out


def main() -> int:
    args = parse_args()
    scale_cfg = SCALES[args.scale]
    args.out.mkdir(parents=True, exist_ok=True)
    trials = []
    for i in range(args.trials):
        print(f"[benchmark] trial {i + 1}/{args.trials}", file=sys.stderr)
        trials.append(_run_trial(scale_cfg))
    record = {
        "label": args.label or "unlabeled",
        "scale": args.scale,
        "scale_cfg": scale_cfg,
        "trials": trials,
        "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "python": sys.version.split()[0],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_label = (args.label or "unlabeled").replace("/", "_").replace(" ", "_")
    out_path = args.out / f"{stamp}-{args.scale}-{safe_label}.json"
    out_path.write_text(json.dumps(record, indent=2))
    print(f"[benchmark] wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
