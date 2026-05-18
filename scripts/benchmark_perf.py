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


def main() -> int:
    args = parse_args()
    scale = SCALES[args.scale]
    print(f"[benchmark] scale={args.scale} {scale}", file=sys.stderr)
    # TODO Task 6: run trials, capture perf lines, write JSON.
    return 0


if __name__ == "__main__":
    sys.exit(main())
