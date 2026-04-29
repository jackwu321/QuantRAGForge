from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from kb_shared import ROOT
import _web_extract
import _pdf_extract


ARTICLES_RAW_DIR = ROOT / "articles" / "raw"


def _is_wechat_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host.endswith("mp.weixin.qq.com")


def _is_pdf_url(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".pdf")


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^a-zA-Z0-9一-鿿]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].lower() or "untitled"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _dispatch_wechat(url: str, content_type: str | None = None, force: bool = False) -> str:
    """Delegate to existing WeChat ingest pipeline."""
    from ingest_wechat_article import ingest_single_url
    args = argparse.Namespace(title=None, content_type=content_type, dry_run=False, force=force)
    result = ingest_single_url(url, args)
    if result.success:
        return result.output_dir
    raise RuntimeError(result.error or "wechat ingest failed")


def write_web_article(
    article: _web_extract.ExtractedArticle,
    articles_root: Path = ARTICLES_RAW_DIR,
    content_type: str = "methodology",
) -> Path:
    host = urlparse(article.source_url).hostname or "unknown"
    slug = _slugify(article.title or "untitled")
    out_dir = articles_root / f"{_today()}_{host}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    fm = [
        "---",
        f"title: {article.title}",
        f"source_url: {article.source_url}",
        f"source_type: web",
        f"content_type: {content_type}",
        f"has_code: {str(article.has_code).lower()}",
        f"has_math: {str(article.has_math).lower()}",
        f"has_formula_images: false",
        f"extraction_quality: {article.extraction_quality}",
        f"paywalled: {str(article.paywalled).lower()}",
        f"status: raw",
        "---",
        "",
        f"# {article.title}",
        "",
        "## Main Content",
        "",
        article.markdown,
        "",
    ]
    (out_dir / "article.md").write_text("\n".join(fm), encoding="utf-8")
    (out_dir / "source.json").write_text(
        json.dumps(
            {
                "source_url": article.source_url,
                "source_type": "web",
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
                "llm_enriched": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


def write_pdf_article(
    pdf: _pdf_extract.ExtractedPdf,
    pdf_path: Path,
    articles_root: Path = ARTICLES_RAW_DIR,
    content_type: str = "methodology",
) -> Path:
    slug = _slugify(pdf_path.stem)
    out_dir = articles_root / f"{_today()}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = out_dir / "source.pdf"
    if pdf_path.resolve() != target_pdf.resolve():
        target_pdf.write_bytes(pdf_path.read_bytes())

    fm = [
        "---",
        f"title: {pdf_path.stem}",
        f"source_path: {pdf_path}",
        f"source_type: pdf",
        f"content_type: {content_type}",
        f"has_code: {str(pdf.has_code).lower()}",
        f"has_math: {str(pdf.has_math).lower()}",
        f"has_formula_images: false",
        f"extraction_quality: {pdf.extraction_quality}",
        f"page_count: {pdf.page_count}",
        f"status: raw",
        "---",
        "",
        f"# {pdf_path.stem}",
        "",
        "## Main Content",
        "",
        pdf.text,
        "",
    ]
    (out_dir / "article.md").write_text("\n".join(fm), encoding="utf-8")
    (out_dir / "source.json").write_text(
        json.dumps(
            {
                "source_path": str(pdf_path),
                "source_type": "pdf",
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
                "llm_enriched": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


def _dispatch_web(url: str, content_type: str | None = None, force: bool = False) -> str:
    article = _web_extract.extract_from_url(url)
    if not article.text.strip():
        raise RuntimeError(f"web extraction returned empty: {url}")
    out_dir = write_web_article(article, content_type=content_type or "methodology")
    return str(out_dir)


def _dispatch_pdf_url(url: str, content_type: str | None = None, force: bool = False) -> str:
    import requests
    response = requests.get(url, timeout=(10, 60))
    response.raise_for_status()
    tmp_path = ARTICLES_RAW_DIR / "_tmp.pdf"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(response.content)
    try:
        pdf = _pdf_extract.extract_from_file(tmp_path)
        return str(write_pdf_article(pdf, tmp_path, content_type=content_type or "methodology"))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def dispatch_url(url: str, content_type: str | None = None, force: bool = False) -> str:
    if _is_wechat_url(url):
        return _dispatch_wechat(url, content_type=content_type, force=force)
    if _is_pdf_url(url):
        return _dispatch_pdf_url(url, content_type=content_type, force=force)
    return _dispatch_web(url, content_type=content_type, force=force)


def dispatch_pdf_file(path: str, content_type: str | None = None) -> str:
    p = Path(path).expanduser().resolve()
    pdf = _pdf_extract.extract_from_file(p)
    return str(write_pdf_article(pdf, p, content_type=content_type or "methodology"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a source (WeChat URL, web URL, PDF URL, PDF file, HTML file).")
    parser.add_argument("--url", help="Single URL (auto-detected: wechat / pdf / web)")
    parser.add_argument("--url-list", help="File with one URL per line")
    parser.add_argument("--html-file", help="Local HTML file path")
    parser.add_argument("--pdf-file", help="Local PDF file path")
    parser.add_argument("--pdf-url", help="Remote PDF URL")
    parser.add_argument("--content-type", help="Content type override")
    parser.add_argument("--force", action="store_true", help="Override duplicate detection")
    args = parser.parse_args()

    if args.url:
        out = dispatch_url(args.url, content_type=args.content_type, force=args.force)
        print(f"Ingested: {out}")
        return 0
    if args.pdf_file:
        out = dispatch_pdf_file(args.pdf_file, content_type=args.content_type)
        print(f"Ingested PDF: {out}")
        return 0
    if args.pdf_url:
        out = _dispatch_pdf_url(args.pdf_url, content_type=args.content_type, force=args.force)
        print(f"Ingested PDF: {out}")
        return 0
    if args.html_file:
        from ingest_wechat_article import extract_article_data, write_article
        html = Path(args.html_file).expanduser().read_text(encoding="utf-8")
        article = extract_article_data(html, "", None)
        if args.content_type:
            article.content_type = args.content_type
        out_dir = write_article(article, force=args.force)
        print(f"Ingested HTML: {out_dir}")
        return 0
    if args.url_list:
        for url in [line.strip() for line in Path(args.url_list).read_text(encoding="utf-8").splitlines() if line.strip()]:
            try:
                out = dispatch_url(url, content_type=args.content_type, force=args.force)
                print(f"Ingested: {out}")
            except Exception as exc:
                print(f"FAILED {url}: {exc}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
