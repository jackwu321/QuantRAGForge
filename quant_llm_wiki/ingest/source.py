from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from quant_llm_wiki.paths import resolve_kb_root
import quant_llm_wiki.ingest.web as _web_extract
import quant_llm_wiki.ingest.pdf as _pdf_extract


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


def _dispatch_wechat(url: str, content_type: str | None = None, force: bool = False, *, kb_root: Path) -> str:
    """Delegate to existing WeChat ingest pipeline."""
    from quant_llm_wiki.ingest.wechat import ingest_single_url, DuplicateArticleError
    result = ingest_single_url(
        url,
        kb_root=kb_root,
        title=None,
        content_type=content_type,
        dry_run=False,
        force=force,
    )
    if result.skipped:
        raise DuplicateArticleError(result.output_dir)
    if result.success:
        return result.output_dir
    raise RuntimeError(result.error or "wechat ingest failed")


def write_web_article(
    article: _web_extract.ExtractedArticle,
    content_type: str = "methodology",
    *,
    kb_root: Path,
) -> Path:
    articles_root = kb_root / "raw"
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
    content_type: str = "methodology",
    *,
    kb_root: Path,
) -> Path:
    articles_root = kb_root / "raw"
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


def _dispatch_web(url: str, content_type: str | None = None, force: bool = False, *, kb_root: Path) -> str:
    article = _web_extract.extract_from_url(url)
    if not article.text.strip():
        raise RuntimeError(f"web extraction returned empty: {url}")
    out_dir = write_web_article(article, content_type=content_type or "methodology", kb_root=kb_root)
    return str(out_dir)


def _dispatch_pdf_url(url: str, content_type: str | None = None, force: bool = False, *, kb_root: Path) -> str:
    import requests
    response = requests.get(url, timeout=(10, 60))
    response.raise_for_status()
    articles_raw_dir = kb_root / "raw"
    tmp_path = articles_raw_dir / "_tmp.pdf"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(response.content)
    try:
        pdf = _pdf_extract.extract_from_file(tmp_path)
        return str(write_pdf_article(pdf, tmp_path, content_type=content_type or "methodology", kb_root=kb_root))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def dispatch_url(url: str, content_type: str | None = None, force: bool = False, *, kb_root: Path) -> str:
    if _is_wechat_url(url):
        return _dispatch_wechat(url, content_type=content_type, force=force, kb_root=kb_root)
    if _is_pdf_url(url):
        return _dispatch_pdf_url(url, content_type=content_type, force=force, kb_root=kb_root)
    return _dispatch_web(url, content_type=content_type, force=force, kb_root=kb_root)


DEFAULT_INGEST_URL_TIMEOUT = 120


def _ingest_url_timeout() -> int:
    try:
        return int(os.environ.get("INGEST_URL_TIMEOUT", DEFAULT_INGEST_URL_TIMEOUT))
    except ValueError:
        return DEFAULT_INGEST_URL_TIMEOUT


def _run_with_timeout(fn, *args, **kwargs):
    timeout = _ingest_url_timeout()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        finally:
            ex.shutdown(wait=False)
    except BaseException:
        ex.shutdown(wait=False)
        raise


def dispatch_pdf_file(path: str, content_type: str | None = None, *, kb_root: Path) -> str:
    p = Path(path).expanduser().resolve()
    pdf = _pdf_extract.extract_from_file(p)
    return str(write_pdf_article(pdf, p, content_type=content_type or "methodology", kb_root=kb_root))


@dataclass
class DispatchResult:
    url: str
    success: bool
    output_dir: str = ""
    error: str = ""


def dispatch_url_list(
    path: Path,
    content_type: str | None = None,
    force: bool = False,
    *,
    kb_root: Path,
) -> list[DispatchResult]:
    """Ingest every non-blank URL from a file, one per line. Returns results."""
    results: list[DispatchResult] = []
    urls = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for url in urls:
        try:
            out = _run_with_timeout(dispatch_url, url, content_type=content_type, force=force, kb_root=kb_root)
            results.append(DispatchResult(url=url, success=True, output_dir=out))
            print(f"Ingested: {out}")
        except FuturesTimeoutError:
            print(f"TIMEOUT {url}: exceeded {_ingest_url_timeout()}s")
            results.append(DispatchResult(url=url, success=False, error="timeout"))
        except Exception as exc:
            print(f"FAILED {url}: {exc}")
            results.append(DispatchResult(url=url, success=False, error=str(exc)))
    return results


def dispatch_html_file(path: Path, content_type: str | None = None, *, kb_root: Path) -> str:
    """Ingest a locally saved HTML file via the WeChat extraction pipeline."""
    from quant_llm_wiki.ingest.wechat import extract_article_data, write_article
    html = path.read_text(encoding="utf-8")
    article = extract_article_data(html, "", None)
    if content_type:
        article.content_type = content_type
    out_dir = write_article(article, force=False, kb_root=kb_root)
    return str(out_dir)


def run_ingest_source(
    kb_root: Path,
    *,
    url: str | None = None,
    url_list: str | None = None,
    html_file: str | None = None,
    pdf_file: str | None = None,
    pdf_url: str | None = None,
    content_type: str | None = None,
    force: bool = False,
    no_compile: bool = False,
) -> int:
    """Business logic for `qlw ingest`. kb_root must be already resolved."""
    if url:
        try:
            out = _run_with_timeout(
                dispatch_url, url, content_type=content_type, force=force, kb_root=kb_root
            )
        except FuturesTimeoutError:
            print(f"TIMEOUT {url}: exceeded {_ingest_url_timeout()}s")
            return 2
        print(f"Ingested: {out}")
    elif url_list:
        results = dispatch_url_list(
            Path(url_list).expanduser().resolve(),
            content_type=content_type,
            force=force,
            kb_root=kb_root,
        )
        ok = sum(1 for r in results if r.success)
        print(f"Ingested: {ok}/{len(results)}")
    elif html_file:
        out = dispatch_html_file(
            Path(html_file).expanduser().resolve(),
            content_type=content_type,
            kb_root=kb_root,
        )
        print(f"Ingested HTML: {out}")
    elif pdf_file:
        out = dispatch_pdf_file(pdf_file, content_type=content_type, kb_root=kb_root)
        print(f"Ingested PDF: {out}")
    elif pdf_url:
        try:
            out = _run_with_timeout(
                _dispatch_pdf_url, pdf_url, content_type=content_type, force=force, kb_root=kb_root
            )
        except FuturesTimeoutError:
            print(f"TIMEOUT {pdf_url}: exceeded {_ingest_url_timeout()}s")
            return 2
        print(f"Ingested PDF URL: {out}")
    else:
        import sys
        print(
            "error: provide one of --url / --url-list / --html-file / --pdf-file / --pdf-url",
            file=sys.stderr,
        )
        return 2

    if not no_compile:
        from quant_llm_wiki.wiki.compile import compile_wiki
        from quant_llm_wiki.embed import run_embed
        report = compile_wiki(kb_root, mode="incremental", dry_run=False, verbose=False)
        if report.errors:
            return 1
        rc = run_embed(kb_root, source_dir="reviewed,high-value", force=False, dry_run=False)
        if rc != 0:
            return rc

    return 0


def _run(args) -> int:
    """Handler for `qlw ingest`."""
    return run_ingest_source(
        resolve_kb_root(getattr(args, "kb_root", None)),
        url=args.url,
        url_list=args.url_list,
        html_file=args.html_file,
        pdf_file=args.pdf_file,
        pdf_url=args.pdf_url,
        content_type=args.content_type,
        force=args.force,
        no_compile=args.no_compile,
    )


def register(parser: argparse.ArgumentParser) -> None:
    """Attach this module's CLI flags to `parser`. Called by quant_llm_wiki.cli."""
    parser.add_argument("--kb-root", default=None, help="Knowledge base root (default: $QLW_KB_ROOT or cwd).")
    parser.add_argument("--url", help="Single URL (auto-detected: wechat / pdf / web).")
    parser.add_argument("--url-list", help="File with one URL per line.")
    parser.add_argument("--html-file", help="Local HTML file path.")
    parser.add_argument("--pdf-file", help="Local PDF file path.")
    parser.add_argument("--pdf-url", help="Remote PDF URL.")
    parser.add_argument("--content-type", help="Content type override.")
    parser.add_argument("--force", action="store_true", help="Override duplicate detection.")
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Skip the auto compile + embed after writing raw/.",
    )
    parser.set_defaults(func=_run)
