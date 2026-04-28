from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency at runtime
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional dependency at runtime
    BeautifulSoup = None

from _wechat import (
    WECHAT_BLOCK_PATTERNS,
    DEFAULT_HEADERS,
    ArticleData,
    ExtractedCodeBlock,
    clean_text,
    sanitize_title,
    detect_blocked_wechat_page,
    extract_article_data,
    fetch_html,
    download_binary,
    infer_extension,
    download_images,
    resolve_url,
    build_summary,
    split_paragraphs,
    infer_research_question,
    infer_core_hypothesis,
    infer_signal_framework,
    classify_content,
    contains_any,
    normalize_date,
    extract_content_container,
    first_non_empty,
    meta_content,
    find_text_by_ids,
    extract_main_content,
    extract_image_urls,
    clone_without_code,
    extract_code_blocks,
    collect_code_nodes,
    is_code_like,
    should_strip_inline_code,
    infer_code_language,
)


ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
ARTICLES_RAW_DIR = ROOT / "articles" / "raw"
SOURCES_PROCESSED_DIR = ROOT / "sources" / "processed"
DEFAULT_URL_LIST = ROOT / "url list.txt"
INGEST_FAILURES_PATH = SOURCES_PROCESSED_DIR / "ingest_failures.txt"

SUPPORTED_CONTENT_TYPES = ("methodology", "strategy", "allocation", "risk_control", "market_review")
IMAGE_SECTION_PLACEHOLDER = "```markdown\n![caption](images/001.png)\n```"
CODE_BLOCK_PLACEHOLDER = "### Code 1\n\n`source: html_code_block | image_ocr`\n\n```python\n# code here\n```"


class DuplicateArticleError(Exception):
    """Raised when an article with the same content already exists."""
    pass


@dataclass
class BatchResult:
    url: str
    success: bool
    output_dir: str = ""
    error: str = ""
    skipped: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest WeChat articles into the local markdown knowledge base."
    )
    parser.add_argument("--url", help="Original article URL.")
    parser.add_argument("--url-list", help="Path to a txt file containing one article URL per line.")
    parser.add_argument("--html-file", help="Path to a previously saved HTML file.")
    parser.add_argument(
        "--title",
        help="Override the detected title. Useful when the page title is noisy.",
    )
    parser.add_argument(
        "--content-type",
        choices=SUPPORTED_CONTENT_TYPES,
        help="Override the detected content_type classification.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even if the article already exists in the knowledge base.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the parsed result without writing files.",
    )
    args = parser.parse_args()
    provided_modes = [bool(args.url), bool(args.url_list), bool(args.html_file)]
    if sum(provided_modes) == 0:
        if DEFAULT_URL_LIST.exists():
            args.url_list = str(DEFAULT_URL_LIST)
        else:
            parser.error("one of --url, --url-list or --html-file is required")
    if sum(bool(x) for x in [args.url, args.url_list, args.html_file]) > 1:
        parser.error("only one of --url, --url-list or --html-file can be used at a time")
    if args.url_list and args.title:
        parser.error("--title is only supported with single article modes")
    return args


def ensure_runtime_dependencies() -> None:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required. Install with: pip install beautifulsoup4")


def read_html(args: argparse.Namespace) -> tuple[str, str]:
    if args.html_file:
        html_path = Path(args.html_file).expanduser().resolve()
        html = html_path.read_text(encoding="utf-8")
        detect_blocked_wechat_page(html)
        return html, ""
    assert args.url
    return fetch_html(args.url), args.url


def load_url_list(path: str) -> list[str]:
    url_list_path = Path(path).expanduser().resolve()
    raw_lines = url_list_path.read_text(encoding="utf-8").splitlines()
    urls: list[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        candidate = normalize_url_line(line)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def normalize_url_line(line: str) -> str:
    candidate = clean_text(line)
    candidate = candidate.strip(";；,，")
    return candidate


def slugify(value: str) -> str:
    value = sanitize_title(value).lower()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "untitled"


def short_hash(*parts: str, length: int = 8) -> str:
    digest = hashlib.sha1("||".join(part.strip() for part in parts if part).encode("utf-8")).hexdigest()
    return digest[:length]


def shorten_slug(value: str, max_length: int = 36) -> str:
    slug = slugify(value)
    if len(slug) <= max_length:
        return slug
    return slug[:max_length].strip("_") or "untitled"


def template_path_for(content_type: str) -> Path:
    if content_type == "strategy":
        return TEMPLATES_DIR / "strategy-note-template.md"
    return TEMPLATES_DIR / "research-note-template.md"


def article_dir_name(article: ArticleData) -> str:
    date_part = article.publish_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", article.publish_date or "") else ""
    date_part = date_part or datetime.now().strftime("%Y-%m-%d")
    slug_part = shorten_slug(article.title)
    unique_part = short_hash(article.title, article.source_url or article.raw_html[:200])
    return f"{date_part}_{slug_part}_{unique_part}"


def build_frontmatter(article: ArticleData) -> dict:
    ingested_at = datetime.now().strftime("%Y-%m-%d")
    return {
        "title": article.title,
        "source_url": article.source_url,
        "source_type": "wechat_mp" if article.source_url else "html_import",
        "account": article.account,
        "author": article.author,
        "publish_date": article.publish_date,
        "ingested_at": ingested_at,
        "status": "raw",
        "content_type": article.content_type,
        "summary": article.summary,
        "research_question": article.research_question,
        "core_hypothesis": article.core_hypothesis,
        "signal_framework": article.signal_framework,
        "code_quality": "usable" if article.code_blocks else "none",
    }


def inject_frontmatter(template_text: str, frontmatter: dict) -> str:
    lines = template_text.splitlines()
    in_frontmatter = False
    updated: list[str] = []
    for line in lines:
        if line.strip() == "---":
            updated.append(line)
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            key, sep, _ = line.partition(":")
            if sep and key in frontmatter:
                value = frontmatter[key]
                if value:
                    updated.append(f"{key}: {value}")
                    continue
        updated.append(line)
    return "\n".join(updated)


def inject_body_placeholders(template_text: str, article: ArticleData) -> str:
    replacements = {
        "{{title}}": article.title,
        "{{source_url}}": article.source_url,
        "{{account}}": article.account,
        "{{publish_date}}": article.publish_date,
        "待生成。": article.summary or "待补充。",
        "## Research Question\n\n待补充。": f"## Research Question\n\n{article.research_question or '待补充。'}",
        "## Core Hypothesis\n\n待补充。": f"## Core Hypothesis\n\n{article.core_hypothesis or '待补充。'}",
        "## Signal Framework / Decision Framework\n\n待补充。": (
            f"## Signal Framework / Decision Framework\n\n{article.signal_framework or '待补充。'}"
        ),
        "## Signal / Feature Definition\n\n待补充。": (
            f"## Signal / Feature Definition\n\n{article.signal_framework or '待补充。'}"
        ),
        "正文待插入。": article.main_content or "正文提取失败，请人工补充。",
    }
    rendered = template_text
    for old, new in replacements.items():
        rendered = rendered.replace(old, new or "")
    return rendered


def inject_image_section(rendered: str, image_markdown: list[str]) -> str:
    if image_markdown:
        return rendered.replace(IMAGE_SECTION_PLACEHOLDER, "\n".join(image_markdown))
    return rendered.replace(IMAGE_SECTION_PLACEHOLDER, "暂无图片或图片下载失败。")


def render_code_blocks(code_blocks: list[ExtractedCodeBlock]) -> str:
    if not code_blocks:
        return "未发现HTML代码块。"
    sections: list[str] = []
    for index, block in enumerate(code_blocks, start=1):
        sections.append(f"### Code {index}\n")
        sections.append(f"`source: {block.source}`\n")
        sections.append(f"```{block.language}\n{block.content}\n```\n")
    return "\n".join(sections).strip()


def inject_code_section(rendered: str, code_blocks: list[ExtractedCodeBlock]) -> str:
    return rendered.replace(CODE_BLOCK_PLACEHOLDER, render_code_blocks(code_blocks))


def find_existing_article(article: ArticleData) -> Path | None:
    """Check if an article with the same directory name already exists in any stage."""
    dir_name = article_dir_name(article)
    for stage in ("raw", "reviewed", "high-value"):
        candidate = ARTICLES_RAW_DIR.parent / stage / dir_name
        if candidate.exists() and (candidate / "article.md").exists():
            return candidate
    return None


def write_article(article: ArticleData, force: bool = False) -> Path:
    existing = find_existing_article(article)
    if existing and not force:
        raise DuplicateArticleError(str(existing))

    template = template_path_for(article.content_type).read_text(encoding="utf-8")
    template = inject_frontmatter(template, build_frontmatter(article))
    rendered = inject_body_placeholders(template, article)

    article_dir = ARTICLES_RAW_DIR / article_dir_name(article)
    images_dir = article_dir / "images"
    article_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)
    SOURCES_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    image_markdown = download_images(article, images_dir)
    rendered = inject_image_section(rendered, image_markdown)
    rendered = inject_code_section(rendered, article.code_blocks)

    (article_dir / "article.md").write_text(rendered, encoding="utf-8")
    (article_dir / "raw.html").write_text(article.raw_html, encoding="utf-8")
    source_payload = {
        "title": article.title,
        "source_url": article.source_url,
        "account": article.account,
        "author": article.author,
        "publish_date": article.publish_date,
        "content_type": article.content_type,
        "summary": article.summary,
        "research_question": article.research_question,
        "core_hypothesis": article.core_hypothesis,
        "signal_framework": article.signal_framework,
        "image_urls": article.image_urls,
        "code_blocks": [
            {"language": block.language, "source": block.source, "content": block.content}
            for block in article.code_blocks
        ],
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    (article_dir / "source.json").write_text(
        json.dumps(source_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return article_dir


def print_summary(article: ArticleData) -> None:
    payload = {
        "title": article.title,
        "content_type": article.content_type,
        "publish_date": article.publish_date,
        "account": article.account,
        "source_url": article.source_url,
        "summary": article.summary,
        "research_question": article.research_question,
        "image_urls": article.image_urls,
        "code_blocks": len(article.code_blocks),
        "main_content_preview": article.main_content[:300],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def ingest_single_url(url: str, args: argparse.Namespace) -> BatchResult:
    try:
        html = fetch_html(url)
        article = extract_article_data(html, url, args.title)
        if args.content_type:
            article.content_type = args.content_type
        if args.dry_run:
            print_summary(article)
            return BatchResult(url=url, success=True)
        force = getattr(args, "force", False)
        out_dir = write_article(article, force=force)
        return BatchResult(url=url, success=True, output_dir=str(out_dir))
    except DuplicateArticleError as exc:
        return BatchResult(url=url, success=True, output_dir=str(exc), skipped=True)
    except Exception as exc:
        return BatchResult(url=url, success=False, error=str(exc))


def classify_ingest_error(error: str) -> str:
    lowered = error.lower()
    if "verification/blocked page" in lowered or "去验证" in error or "环境异常" in error:
        return "blocked_wechat_page"
    return "ingest_error"


def write_ingest_failures(results: list[BatchResult]) -> Path:
    SOURCES_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{result.url}\t{classify_ingest_error(result.error)}\t{result.error}"
        for result in results
        if not result.success
    ]
    INGEST_FAILURES_PATH.write_text("\n".join(lines), encoding="utf-8")
    return INGEST_FAILURES_PATH


def ingest_url_list(path: str, args: argparse.Namespace) -> int:
    urls = load_url_list(path)
    if not urls:
        print("no valid urls found in list")
        return 1

    results: list[BatchResult] = []
    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] ingesting {url}")
        result = ingest_single_url(url, args)
        results.append(result)
        if result.skipped:
            print(f"  skipped (already exists): {result.output_dir}")
        elif result.success:
            if result.output_dir:
                print(f"  created: {result.output_dir}")
            else:
                print("  parsed successfully")
        else:
            print(f"  failed: {result.error}")

    success_count = sum(1 for r in results if r.success and not r.skipped)
    skipped_count = sum(1 for r in results if r.skipped)
    failure_count = sum(1 for r in results if not r.success)
    failure_list_path = write_ingest_failures(results)
    summary = {
        "total": len(results),
        "success": success_count,
        "skipped": skipped_count,
        "failed": failure_count,
        "failure_list_path": str(failure_list_path),
        "failed_urls": [
            {"url": r.url, "error": r.error, "error_type": classify_ingest_error(r.error)}
            for r in results
            if not r.success
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failure_count == 0 else 1


def main() -> int:
    args = parse_args()
    if args.url_list:
        return ingest_url_list(args.url_list, args)

    html, detected_url = read_html(args)
    source_url = args.url or detected_url
    article = extract_article_data(html, source_url, args.title)
    if args.content_type:
        article.content_type = args.content_type

    if args.dry_run:
        print_summary(article)
        return 0

    try:
        out_dir = write_article(article, force=args.force)
    except DuplicateArticleError as exc:
        print(f"skipped (already exists): {exc}")
        print("use --force to re-ingest")
        return 0
    print(f"created: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


