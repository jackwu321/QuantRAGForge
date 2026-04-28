from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
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


def clean_text(value: str) -> str:
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def sanitize_title(title: str) -> str:
    title = clean_text(title)
    title = re.sub(r"[\\/:*?\"<>|：？""''《》【】｜]+", "_", title)
    title = re.sub(r"[\x00-\x1f]+", "_", title)
    title = re.sub(r"\s+", " ", title).strip(" ._")
    title = re.sub(r"_+", "_", title)
    return title[:80].strip(" ._") or "untitled"


def detect_blocked_wechat_page(html: str) -> None:
    lowered = html.lower()
    if any(pattern.lower() in lowered for pattern in WECHAT_BLOCK_PATTERNS):
        raise RuntimeError(
            "wechat returned a verification/blocked page instead of the article content; "
            "open the link in a browser and save the full HTML, then use --html-file"
        )


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


def extract_content_container(soup: BeautifulSoup):
    return soup.find(id="js_content") or soup.find("article") or soup.find("main") or soup.find("body")


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


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return [p for p in paragraphs if len(p) >= 8]


def build_summary(main_content: str) -> str:
    paragraphs = split_paragraphs(main_content)
    if not paragraphs:
        return ""
    summary = "\n\n".join(paragraphs[:2])
    return summary[:400]


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


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


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


def infer_extension(image_url: str, content_type: str) -> str:
    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else None
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".jpg"


def extract_article_data(html: str, source_url: str, title_override: Optional[str]) -> ArticleData:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required. Install with: pip install beautifulsoup4")
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
