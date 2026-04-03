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


ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
ARTICLES_RAW_DIR = ROOT / "articles" / "raw"
SOURCES_PROCESSED_DIR = ROOT / "sources" / "processed"
DEFAULT_URL_LIST = ROOT / "url list.txt"
INGEST_FAILURES_PATH = SOURCES_PROCESSED_DIR / "ingest_failures.txt"

SUPPORTED_CONTENT_TYPES = ("methodology", "strategy", "allocation", "risk_control", "market_review")
IMAGE_SECTION_PLACEHOLDER = "```markdown\n![caption](images/001.png)\n```"
CODE_BLOCK_PLACEHOLDER = "### Code 1\n\n`source: html_code_block | image_ocr`\n\n```python\n# code here\n```"
WECHAT_BLOCK_PATTERNS = (
    "环境异常",
    "当前环境异常，完成验证后即可继续访问",
    "去验证",
    "secitptpage/verify",
)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass
class ExtractedCodeBlock:
    language: str
    content: str
    source: str = "html_code_block"


@dataclass
class ArticleData:
    title: str
    source_url: str
    account: str
    author: str
    publish_date: str
    raw_html: str
    main_content: str
    content_type: str
    image_urls: list[str]
    summary: str
    research_question: str
    core_hypothesis: str
    signal_framework: str
    code_blocks: list[ExtractedCodeBlock]


@dataclass
class BatchResult:
    url: str
    success: bool
    output_dir: str = ""
    error: str = ""


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


def fetch_html(url: str) -> str:
    if requests is None:
        raise RuntimeError("requests is required for --url mode. Install with: pip install requests")
    response = requests.get(url, timeout=20, headers=DEFAULT_HEADERS)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    html = response.text
    detect_blocked_wechat_page(html)
    return html


def download_binary(url: str) -> tuple[bytes, str]:
    if requests is None:
        raise RuntimeError("requests is required for image download. Install with: pip install requests")
    response = requests.get(url, timeout=30, headers=DEFAULT_HEADERS)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    return response.content, content_type


def detect_blocked_wechat_page(html: str) -> None:
    lowered = html.lower()
    if any(pattern.lower() in lowered for pattern in WECHAT_BLOCK_PATTERNS):
        raise RuntimeError(
            "wechat returned a verification/blocked page instead of the article content; "
            "open the link in a browser and save the full HTML, then use --html-file"
        )


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


def clean_text(value: str) -> str:
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_article_data(html: str, source_url: str, title_override: Optional[str]) -> ArticleData:
    ensure_runtime_dependencies()
    soup = BeautifulSoup(html, "html.parser")
    container = extract_content_container(soup)

    title = title_override or first_non_empty(
        meta_content(soup, "property", "og:title"),
        meta_content(soup, "name", "twitter:title"),
        soup.title.string if soup.title and soup.title.string else "",
    )
    title = sanitize_title(title or "untitled")

    account = first_non_empty(
        meta_content(soup, "name", "author"),
        find_text_by_ids(soup, ["js_name", "profileBt", "js_profile_qrcode"]),
        "",
    )

    publish_date = first_non_empty(
        meta_content(soup, "property", "article:published_time"),
        find_text_by_ids(soup, ["publish_time", "activity-name"]),
        "",
    )
    publish_date = normalize_date(publish_date)

    author = ""
    main_content = extract_main_content(container)
    image_urls = extract_image_urls(container, source_url)
    code_blocks = extract_code_blocks(container)
    content_type = classify_content(title=title, text=main_content)
    summary = build_summary(main_content)
    research_question = infer_research_question(title, main_content)
    core_hypothesis = infer_core_hypothesis(main_content)
    signal_framework = infer_signal_framework(content_type, title, main_content)
    return ArticleData(
        title=title,
        source_url=source_url,
        account=account,
        author=author,
        publish_date=publish_date,
        raw_html=html,
        main_content=main_content,
        content_type=content_type,
        image_urls=image_urls,
        summary=summary,
        research_question=research_question,
        core_hypothesis=core_hypothesis,
        signal_framework=signal_framework,
        code_blocks=code_blocks,
    )


def extract_content_container(soup: BeautifulSoup):
    return soup.find(id="js_content") or soup.find("article") or soup.find("main") or soup.find("body")


def first_non_empty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return clean_text(value)
    return ""


def meta_content(soup: BeautifulSoup, attr_name: str, attr_value: str) -> str:
    node = soup.find("meta", attrs={attr_name: attr_value})
    return node.get("content", "") if node else ""


def find_text_by_ids(soup: BeautifulSoup, ids: list[str]) -> str:
    for node_id in ids:
        node = soup.find(id=node_id)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def normalize_date(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", value)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def extract_main_content(container) -> str:
    if not container:
        return ""
    text_container = clone_without_code(container)
    text = text_container.get_text("\n", strip=True)
    return clean_text(text)


def extract_image_urls(container, source_url: str) -> list[str]:
    if not container:
        return []

    image_urls: list[str] = []
    seen: set[str] = set()
    for img in container.find_all("img"):
        candidate = first_non_empty(
            img.get("data-src", ""),
            img.get("src", ""),
            img.get("data-original", ""),
        )
        if not candidate:
            continue
        resolved = resolve_url(candidate, source_url)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        image_urls.append(resolved)
    return image_urls


def clone_without_code(container):
    cloned = BeautifulSoup(str(container), "html.parser")
    root = cloned.find()
    if not root:
        return cloned
    for node in root.find_all("pre"):
        node.decompose()
    for node in root.find_all("code"):
        if node.find_parent("pre") is not None:
            continue
        if should_strip_inline_code(clean_text(node.get_text("\n", strip=True))):
            node.decompose()
    return root


def extract_code_blocks(container) -> list[ExtractedCodeBlock]:
    if not container:
        return []

    pre_nodes = container.find_all("pre")
    if pre_nodes:
        return collect_code_nodes(pre_nodes)

    code_nodes = []
    for node in container.find_all("code"):
        if node.find_parent("pre") is not None:
            continue
        code_nodes.append(node)
    return collect_code_nodes(code_nodes, require_code_like=True)


def collect_code_nodes(nodes, require_code_like: bool = False) -> list[ExtractedCodeBlock]:
    blocks: list[ExtractedCodeBlock] = []
    seen: set[str] = set()
    for node in nodes:
        text = clean_text(node.get_text("\n", strip=True))
        if not text:
            continue
        if require_code_like and not is_code_like(text):
            continue
        if not require_code_like and len(text) < 20:
            continue
        if text in seen:
            continue
        seen.add(text)
        language = infer_code_language(node, text)
        blocks.append(ExtractedCodeBlock(language=language, content=text))
    return blocks


def is_code_like(text: str) -> bool:
    if len(text) < 20:
        return False
    if "\n" in text:
        return True
    code_markers = ["def ", "class ", "return", "import ", "=", "(", ")", "[", "]", "{", "}", ":"]
    return sum(marker in text for marker in code_markers) >= 2


def should_strip_inline_code(text: str) -> bool:
    if not text or len(text) < 8:
        return False
    if "\n" in text:
        return True
    inline_markers = ["def ", "class ", "return", "import ", "=", "(", ")", "[", "]", "{", "}", ":", ".", ","]
    return sum(marker in text for marker in inline_markers) >= 1


def infer_code_language(node, text: str) -> str:
    classes = " ".join(node.get("class", []))
    attrs = f"{classes} {node.get('data-lang', '')} {node.get('lang', '')}".lower()
    mapping = {
        "python": "python",
        "javascript": "javascript",
        "sql": "sql",
        "bash": "bash",
        "shell": "bash",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "cpp": "cpp",
        "java": "java",
    }
    for key, value in mapping.items():
        if key in attrs:
            return value
    stripped = text.lstrip().lower()
    if stripped.startswith(("def ", "class ", "import ", "from ")):
        return "python"
    if stripped.startswith(("select ", "with ", "insert ", "update ", "delete ")):
        return "sql"
    if stripped.startswith(("{", "[")):
        return "json"
    return "text"


def build_summary(main_content: str) -> str:
    paragraphs = split_paragraphs(main_content)
    if not paragraphs:
        return ""
    summary = "\n\n".join(paragraphs[:2])
    return summary[:400]


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return [p for p in paragraphs if len(p) >= 8]


def infer_research_question(title: str, main_content: str) -> str:
    title = title.strip()
    if re.search(r"如何|怎样|怎么|实现|建立|构建|应用", title):
        return title
    paragraphs = split_paragraphs(main_content)
    if paragraphs:
        return f"本文主要讨论：{paragraphs[0][:120]}"
    return ""


def infer_core_hypothesis(main_content: str) -> str:
    paragraphs = split_paragraphs(main_content)
    if not paragraphs:
        return ""
    return paragraphs[0][:200]


def infer_signal_framework(content_type: str, title: str, main_content: str) -> str:
    if content_type == "allocation":
        return "围绕筛选、排序、权重分配与再平衡的配置框架。"
    if content_type == "risk_control":
        return "围绕风险识别、仓位约束、波动率控制、回撤管理或风险预算的风控框架。"
    if content_type == "strategy":
        return "围绕信号生成、入场退出与持有更新的策略框架。"
    if content_type == "market_review":
        return "围绕市场观察、阶段判断与后续跟踪的复盘框架。"
    if "transformer" in title.lower() or "cnn" in title.lower():
        return "围绕模型结构、特征输入与预测流程的方法框架。"
    return "围绕文中核心方法、假设与适用场景的研究框架。"


def classify_content(title: str, text: str) -> str:
    combined = f"{title}\n{text}".lower()
    allocation_keywords = (
        "行业轮动",
        "主题轮动",
        "资产配置",
        "组合配置",
        "etf",
        "权重",
        "再平衡",
        "allocation",
        "rotation",
    )
    strategy_keywords = (
        "开仓",
        "平仓",
        "止损",
        "买入",
        "卖出",
        "信号",
        "调仓",
        "回测",
        "strategy",
        "sharpe",
    )
    risk_control_keywords = (
        "风控",
        "风险控制",
        "风险预算",
        "仓位控制",
        "头寸管理",
        "波动率目标",
        "volatility targeting",
        "回撤控制",
        "最大回撤",
        "止损机制",
        "风险平价",
        "risk parity",
        "hedging",
        "对冲",
        "regime filter",
    )
    market_review_keywords = (
        "复盘",
        "点评",
        "周报",
        "月报",
        "观察",
        "市场回顾",
        "盘面",
    )

    if contains_any(combined, allocation_keywords):
        return "allocation"
    if contains_any(combined, risk_control_keywords):
        return "risk_control"
    if contains_any(combined, strategy_keywords):
        return "strategy"
    if contains_any(combined, market_review_keywords):
        return "market_review"
    return "methodology"


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def resolve_url(value: str, base_url: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith(("http://", "https://")):
        return value
    if base_url:
        return urljoin(base_url, value)
    return value


def sanitize_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"[\\/:*?\"<>|：？“”‘’《》【】｜]+", "_", title)
    title = re.sub(r"[\x00-\x1f]+", "_", title)
    title = re.sub(r"\s+", " ", title).strip(" ._")
    title = re.sub(r"_+", "_", title)
    return title[:80].strip(" ._") or "untitled"


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


def infer_extension(image_url: str, content_type: str) -> str:
    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else None
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".jpg"


def download_images(article: ArticleData, images_dir: Path) -> list[str]:
    image_markdown: list[str] = []
    for index, image_url in enumerate(article.image_urls, start=1):
        try:
            data, content_type = download_binary(image_url)
        except Exception:
            image_markdown.append(f"<!-- image download failed: {image_url} -->")
            continue
        extension = infer_extension(image_url, content_type)
        filename = f"{index:03d}{extension}"
        output_path = images_dir / filename
        output_path.write_bytes(data)
        image_markdown.append(f"![image_{index}](images/{filename})")
    return image_markdown


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


def write_article(article: ArticleData) -> Path:
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
        out_dir = write_article(article)
        return BatchResult(url=url, success=True, output_dir=str(out_dir))
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
        if result.success:
            if result.output_dir:
                print(f"  created: {result.output_dir}")
            else:
                print("  parsed successfully")
        else:
            print(f"  failed: {result.error}")

    success_count = sum(1 for r in results if r.success)
    failure_count = len(results) - success_count
    failure_list_path = write_ingest_failures(results)
    summary = {
        "total": len(results),
        "success": success_count,
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

    out_dir = write_article(article)
    print(f"created: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


