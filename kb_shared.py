from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - runtime dependency
    requests = None

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

# Auto-load .env from project root (does not override existing env vars)
load_dotenv(ROOT / ".env")
DEFAULT_SOURCE_DIRS = ("reviewed", "high-value")
WIKI_DIR = ROOT / "wiki"
WIKI_CONCEPTS_DIR = WIKI_DIR / "concepts"
WIKI_SOURCES_DIR = WIKI_DIR / "sources"
WIKI_INDEX_PATH = WIKI_DIR / "INDEX.md"

# ---------------------------------------------------------------------------
# LLM provider configuration (OpenAI-compatible API)
# ---------------------------------------------------------------------------
# Supports any provider with an OpenAI-compatible endpoint:
#   Zhipu GLM, DeepSeek, Moonshot, Qwen, OpenAI, Ollama, vLLM, etc.
#
# Environment variables (new generic names, with ZHIPU_* fallbacks):
#   LLM_API_KEY         / ZHIPU_API_KEY          — API key
#   LLM_BASE_URL        / ZHIPU_BASE_URL         — Base URL for the API
#   LLM_MODEL           / ZHIPU_MODEL            — Chat model name
#   LLM_EMBEDDING_MODEL / ZHIPU_EMBEDDING_MODEL  — Embedding model name
#   LLM_CONNECT_TIMEOUT / ZHIPU_CONNECT_TIMEOUT  — Connection timeout in seconds
#   LLM_READ_TIMEOUT    / ZHIPU_READ_TIMEOUT     — Read timeout in seconds
#   LLM_MAX_RETRIES     / ZHIPU_MAX_RETRIES      — Max retry attempts
#   LLM_CONCURRENCY                              — Max parallel LLM requests (default: 3)
# ---------------------------------------------------------------------------

DEFAULT_LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_LLM_MODEL = "glm-4.7"
DEFAULT_EMBEDDING_MODEL = "embedding-3"
DEFAULT_CONNECT_TIMEOUT = 15
DEFAULT_READ_TIMEOUT = 180
DEFAULT_MAX_RETRIES = 2
DEFAULT_LLM_CONCURRENCY = 3
PLACEHOLDER_TEXTS = {"待补充。", "待生成。"}


class LLMAuthError(RuntimeError):
    """Raised when the LLM API returns a 401/403 authentication error."""


# ---------------------------------------------------------------------------
# Rejected sources registry — tracks URLs/titles marked as low-value
# ---------------------------------------------------------------------------
REJECTED_SOURCES_PATH = ROOT / "rejected_sources.json"


def load_rejected_sources() -> list[dict[str, str]]:
    """Load the rejected sources list. Each entry has 'source_url', 'title', 'reason', 'rejected_at'."""
    if not REJECTED_SOURCES_PATH.exists():
        return []
    return json.loads(REJECTED_SOURCES_PATH.read_text(encoding="utf-8"))


def save_rejected_sources(entries: list[dict[str, str]]) -> None:
    REJECTED_SOURCES_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def find_rejected_source(source_url: str = "", title: str = "") -> dict[str, str] | None:
    """Check if a URL or title was previously rejected. Returns the entry or None."""
    entries = load_rejected_sources()
    for entry in entries:
        if source_url and entry.get("source_url") and entry["source_url"] == source_url:
            return entry
        if title and entry.get("title") and entry["title"] == title:
            return entry
    return None


def add_rejected_source(source_url: str, title: str, reason: str = "") -> None:
    """Add a source to the rejected list (skips if already present)."""
    from datetime import datetime
    if find_rejected_source(source_url, title):
        return
    entries = load_rejected_sources()
    entries.append({
        "source_url": source_url,
        "title": title,
        "reason": reason,
        "rejected_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_rejected_sources(entries)


# ---------------------------------------------------------------------------
# Vector store health check
# ---------------------------------------------------------------------------

def check_vector_store_health(vector_store_dir: Path) -> bool:
    """Pre-flight check: validate chroma.sqlite3 before Chroma touches it.

    Must be called BEFORE chromadb.PersistentClient() to avoid poisoning
    Chroma's Rust bindings with a corrupt database.

    Returns True if store is healthy or absent (safe to proceed).
    Returns False if store was corrupt and has been cleaned up.
    """
    import shutil
    db_path = vector_store_dir / "chroma.sqlite3"
    if not db_path.exists():
        return True
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        if result and result[0] == "ok":
            return True
    except Exception:
        pass
    # Corrupt — clean up before Chroma touches it
    shutil.rmtree(str(vector_store_dir), ignore_errors=True)
    vector_store_dir.mkdir(parents=True, exist_ok=True)
    # Clear manifest so all articles get re-indexed on next embed
    manifest_path = vector_store_dir / "index_manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    return False


@dataclass
class KnowledgeNote:
    article_dir: Path
    source_dir: str
    frontmatter: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", "")).strip() or self.article_dir.name

    @property
    def effective_status(self) -> str:
        frontmatter_status = str(self.frontmatter.get("status", "")).strip()
        if frontmatter_status and frontmatter_status != "raw":
            return frontmatter_status
        return self.source_dir.replace("-", "_")


@dataclass
class KnowledgeBlock:
    note: KnowledgeNote
    block_type: str
    text: str
    score: float


def require_requests() -> None:
    if requests is None:
        raise RuntimeError("requests is required. Install with: pip install requests")


def parse_csv_arg(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_frontmatter_value(value: str) -> Any:
    if not value:
        return ""
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    parts = markdown.split("---\n", 2)
    if len(parts) < 3:
        return {}, markdown
    frontmatter_text = parts[1]
    body = parts[2]
    data: dict[str, Any] = {}
    for raw_line in frontmatter_text.splitlines():
        key, sep, value = raw_line.partition(":")
        if not sep:
            continue
        data[key.strip()] = parse_frontmatter_value(value.strip())
    return data, body


def discover_article_dirs(kb_root: Path, source_dirs: list[str]) -> list[tuple[str, Path]]:
    discovered: list[tuple[str, Path]] = []
    for source_dir in source_dirs:
        directory = kb_root / "articles" / source_dir
        if not directory.exists():
            continue
        for article_dir in sorted([p for p in directory.iterdir() if p.is_dir()], key=lambda p: p.name):
            if (article_dir / "article.md").exists():
                discovered.append((source_dir, article_dir))
    return discovered


def load_notes(kb_root: Path, source_dirs: list[str]) -> list[KnowledgeNote]:
    notes: list[KnowledgeNote] = []
    for source_dir, article_dir in discover_article_dirs(kb_root, source_dirs):
        markdown = (article_dir / "article.md").read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(markdown)
        notes.append(KnowledgeNote(article_dir=article_dir, source_dir=source_dir, frontmatter=frontmatter, body=body))
    return notes


def matches_filter(note: KnowledgeNote, field: str, expected: list[str]) -> bool:
    if not expected:
        return True
    actual = note.frontmatter.get(field, "")
    if isinstance(actual, list):
        values = {str(item).strip() for item in actual if str(item).strip()}
        return any(item in values for item in expected)
    return str(actual).strip() in expected


def filter_notes(notes: list[KnowledgeNote], content_type: list[str], market: list[str], asset_type: list[str], strategy_type: list[str], brainstorm_value: list[str]) -> list[KnowledgeNote]:
    filtered: list[KnowledgeNote] = []
    for note in notes:
        if note.effective_status not in {"reviewed", "high_value"}:
            continue
        if not matches_filter(note, "content_type", content_type):
            continue
        if not matches_filter(note, "market", market):
            continue
        if not matches_filter(note, "asset_type", asset_type):
            continue
        if not matches_filter(note, "strategy_type", strategy_type):
            continue
        if not matches_filter(note, "brainstorm_value", brainstorm_value):
            continue
        filtered.append(note)
    return filtered


def extract_section(body: str, heading: str) -> str:
    pattern = rf"## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, body, flags=re.S)
    return match.group(1).strip() if match else ""


def build_blocks(note: KnowledgeNote, max_main_content_paragraphs: int = 6) -> list[KnowledgeBlock]:
    frontmatter = note.frontmatter
    blocks: list[KnowledgeBlock] = []

    def add_block(block_type: str, text: Any) -> None:
        cleaned = str(text).strip()
        if cleaned and cleaned not in PLACEHOLDER_TEXTS:
            blocks.append(KnowledgeBlock(note=note, block_type=block_type, text=cleaned, score=0.0))

    add_block("summary", frontmatter.get("summary", ""))
    add_block("core_hypothesis", frontmatter.get("core_hypothesis", ""))
    add_block("research_question", frontmatter.get("research_question", ""))
    add_block("signal_framework", frontmatter.get("signal_framework", ""))

    for key in ("idea_blocks", "combination_hooks", "transfer_targets", "failure_modes"):
        value = frontmatter.get(key, [])
        if isinstance(value, list):
            for item in value:
                add_block(key, item)

    main_content = extract_section(note.body, "Main Content")
    paragraphs = [p.strip() for p in main_content.split("\n") if p.strip()]
    for paragraph in paragraphs[:max_main_content_paragraphs]:
        add_block("main_content", paragraph[:400])
    return blocks


# ---------------------------------------------------------------------------
# LLM provider helpers — generic, OpenAI-compatible
# ---------------------------------------------------------------------------

def _env_with_fallback(generic: str, legacy: str, default: str = "") -> str:
    """Read env var with generic name first, then legacy ZHIPU_* fallback."""
    value = os.getenv(generic, "").strip()
    if value:
        return value
    return os.getenv(legacy, default).strip()


def get_llm_config() -> tuple[str, str, str]:
    """Return (api_key, base_url, model) for the configured LLM provider.

    Key resolution: environment variable LLM_API_KEY (or ZHIPU_API_KEY fallback),
    loaded from .env via python-dotenv at module import time.

    Works with any OpenAI-compatible API provider.
    """
    api_key = _env_with_fallback("LLM_API_KEY", "ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM API key is required. Provide it in one of these ways:\n"
            "  1. Set LLM_API_KEY in .env file in the project root\n"
            "  2. Set the LLM_API_KEY environment variable"
        )
    base_url = _env_with_fallback("LLM_BASE_URL", "ZHIPU_BASE_URL", DEFAULT_LLM_BASE_URL).rstrip("/")
    model = _env_with_fallback("LLM_MODEL", "ZHIPU_MODEL", DEFAULT_LLM_MODEL) or DEFAULT_LLM_MODEL
    return api_key, base_url, model




def _timeouts_for_env() -> tuple[int, int, int]:
    connect_timeout = int(
        _env_with_fallback("LLM_CONNECT_TIMEOUT", "ZHIPU_CONNECT_TIMEOUT", str(DEFAULT_CONNECT_TIMEOUT))
    )
    read_timeout = int(
        _env_with_fallback("LLM_READ_TIMEOUT", "ZHIPU_READ_TIMEOUT", str(DEFAULT_READ_TIMEOUT))
    )
    max_retries = int(
        _env_with_fallback("LLM_MAX_RETRIES", "ZHIPU_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
    )
    return connect_timeout, read_timeout, max_retries


def _is_retryable_status(status_code: int) -> bool:
    """Return True if the HTTP status code is worth retrying."""
    if 400 <= status_code < 500:
        return status_code == 429  # rate limit is retryable
    return True  # 5xx, network errors, etc.


def post_llm_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the LLM provider's OpenAI-compatible API with retries.

    Non-retryable errors (4xx except 429) fail immediately.
    Auth errors (401/403) raise LLMAuthError for fail-fast handling.
    """
    require_requests()
    api_key, base_url, _ = get_llm_config()
    connect_timeout, read_timeout, max_retries = _timeouts_for_env()
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                f"{base_url}{path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=(connect_timeout, read_timeout),
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in (401, 403):
                raise LLMAuthError(
                    f"LLM API authentication failed ({status}). Check your LLM_API_KEY."
                ) from exc
            if not _is_retryable_status(status):
                raise
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(min(1.5, 0.5 * (attempt + 1)))
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(min(1.5, 0.5 * (attempt + 1)))
    if last_error is None:
        raise RuntimeError("LLM API request failed without an explicit exception")
    url = f"{base_url}{path}"
    raise type(last_error)(
        f"LLM API request to {url} failed after {max_retries + 1} attempt(s): "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


# Backward-compatible alias
post_zhipu_json = post_llm_json


def call_llm_chat(messages: list[dict[str, str]], temperature: float = 0.2) -> str:
    """Call the LLM chat completions endpoint (OpenAI-compatible)."""
    _api_key, _base_url, model = get_llm_config()
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    data = post_llm_json("/chat/completions", payload)
    return data["choices"][0]["message"]["content"].strip()


# Backward-compatible alias
call_zhipu_chat = call_llm_chat


def embed_text(text: str, model: str | None = None) -> list[float]:
    """Call the embeddings endpoint (OpenAI-compatible)."""
    embedding_model = model or _env_with_fallback(
        "LLM_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    ) or DEFAULT_EMBEDDING_MODEL
    data = post_llm_json(
        "/embeddings",
        {"model": embedding_model, "input": text},
    )
    return data["data"][0]["embedding"]


def article_content_hash(article_dir: Path, schema_version: str) -> str:
    article_path = article_dir / "article.md"
    digest = hashlib.sha256()
    digest.update(schema_version.encode("utf-8"))
    digest.update(article_path.read_bytes())
    return digest.hexdigest()
