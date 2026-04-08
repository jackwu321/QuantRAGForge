from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ARTICLES_DIR = ROOT / "articles"
DEFAULT_SOURCE_DIR = ARTICLES_DIR / "raw"
STATUS_TO_DIR = {
    "reviewed": "reviewed",
    "high_value": "high-value",
    "high-value": "high-value",
}
REJECTED_STATUSES = {"rejected"}


@dataclass
class SyncResult:
    article_dir: str
    status: str
    target_dir: str
    moved: bool
    reason: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move article folders from raw to reviewed/high-value based on frontmatter status."
    )
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="Source directory, default articles/raw.")
    parser.add_argument("--dry-run", action="store_true", help="Preview moves without changing files.")
    return parser.parse_args()


def parse_status(article_md: Path) -> str:
    text = article_md.read_text(encoding="utf-8", errors="ignore")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            for line in frontmatter.splitlines():
                key, sep, value = line.partition(":")
                if sep and key.strip() == "status":
                    return value.strip()
    match = re.search(r"^status:\s*([^\n\r]+)", text, flags=re.M)
    return match.group(1).strip() if match else ""


def safe_target_dir(base_dir: Path) -> Path:
    if not base_dir.exists():
        return base_dir
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir.parent / f"{base_dir.name}__dup_{suffix}"


def sync_by_status(source_dir: Path, dry_run: bool) -> list[SyncResult]:
    results: list[SyncResult] = []
    if not source_dir.exists():
        return results

    for article_dir in sorted([p for p in source_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
        article_md = article_dir / "article.md"
        if not article_md.exists():
            results.append(
                SyncResult(
                    article_dir=str(article_dir),
                    status="",
                    target_dir="",
                    moved=False,
                    reason="article.md missing",
                )
            )
            continue

        status = parse_status(article_md)

        # Handle rejected articles — remove from raw/
        if status in REJECTED_STATUSES:
            if not dry_run:
                shutil.rmtree(str(article_dir))
            results.append(
                SyncResult(
                    article_dir=str(article_dir),
                    status=status,
                    target_dir="(deleted)",
                    moved=True,
                    reason="rejected — removed from knowledge base",
                )
            )
            continue

        target_name = STATUS_TO_DIR.get(status, "")
        if not target_name:
            results.append(
                SyncResult(
                    article_dir=str(article_dir),
                    status=status,
                    target_dir="",
                    moved=False,
                    reason="status not syncable",
                )
            )
            continue

        target_root = ARTICLES_DIR / target_name
        target_root.mkdir(parents=True, exist_ok=True)
        target_dir = safe_target_dir(target_root / article_dir.name)
        if not dry_run:
            shutil.move(str(article_dir), str(target_dir))
        results.append(
            SyncResult(
                article_dir=str(article_dir),
                status=status,
                target_dir=str(target_dir),
                moved=True,
            )
        )
    return results


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source_dir).expanduser().resolve()
    results = sync_by_status(source_dir, dry_run=args.dry_run)
    moved = [r for r in results if r.moved]
    skipped = [r for r in results if not r.moved]
    summary = {
        "source_dir": str(source_dir),
        "dry_run": bool(args.dry_run),
        "total": len(results),
        "moved": len(moved),
        "skipped": len(skipped),
        "moved_items": [
            {"article_dir": r.article_dir, "status": r.status, "target_dir": r.target_dir}
            for r in moved
        ],
        "skipped_items": [
            {"article_dir": r.article_dir, "status": r.status, "reason": r.reason}
            for r in skipped
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
