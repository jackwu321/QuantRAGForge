from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kb_shared import (
    get_llm_config,
    post_llm_json,
    require_requests,
    _env_with_fallback,
    LLMAuthError,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_LLM_CONCURRENCY,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_ARTICLES_ROOT = ROOT / "articles" / "raw"
SOURCES_PROCESSED_DIR = ROOT / "sources" / "processed"
DEFAULT_STATUS_FILTER = "raw"
LLM_FAILURES_PATH = SOURCES_PROCESSED_DIR / "llm_failures.txt"
DEFAULT_MAIN_CONTENT_LIMIT = 8000
DEFAULT_CODE_BLOCK_LIMIT = 3
DEFAULT_CODE_BLOCK_CHAR_LIMIT = 800
PLACEHOLDER_TEXTS = {
    "待生成。",
    "待补充。",
}
ALLOWED_REUSABILITY = {"idea_only", "adaptable", "directly_implementable"}
ALLOWED_CLAIM_STRENGTH = {"weak", "moderate", "strong"}
ALLOWED_BRAINSTORM_VALUE = {"low", "medium", "high"}
ALLOWED_CONTENT_TYPES = {"methodology", "strategy", "allocation", "risk_control", "market_review"}
ALLOWED_MARKETS = {
    "a_share",
    "hk_equity",
    "us_equity",
    "commodity_futures",
    "index_futures",
    "bond",
    "fx",
    "crypto",
    "multi_asset",
    "general",
}
ALLOWED_ASSET_TYPES = {
    "stock",
    "etf",
    "future",
    "option",
    "bond",
    "currency",
    "crypto_asset",
    "index",
    "sector_basket",
    "multi_asset",
    "general_time_series",
}
ALLOWED_STRATEGY_TYPES = {
    "trend_following",
    "mean_reversion",
    "cross_sectional",
    "time_series_forecast",
    "factor_model",
    "allocation_rotation",
    "event_driven",
    "stat_arb",
    "pair_trading",
    "options_volatility",
    "macro_regime",
    "ml_prediction",
    "risk_model",
    "risk_control",
    "volatility_targeting",
    "drawdown_control",
    "position_sizing",
    "regime_filter",
    "execution_microstructure",
    "seasonal_calendar",
    "momentum",
    "carry",
    "breakout",
    "engineering_system",
}

SYSTEM_PROMPT = """你是量化投研知识库的结构化增强助手。\n你的任务不是总结文章，而是把文章增强为适合知识检索和头脑风暴的结构化知识卡片。\n你必须输出严格 JSON，不要输出 Markdown，不要输出解释，不要输出代码块围栏。\n不得编造不存在的回测结果、代码、市场结论。\n优先抽取可迁移逻辑、可组合逻辑、启发价值。\n如果文章不是明确策略，不要硬填交易字段。"""

USER_PROMPT_TEMPLATE = """请基于以下文章内容输出严格 JSON。\n\n字段要求：\n- research_question: 字符串\n- core_hypothesis: 字符串\n- signal_framework: 字符串\n- application_scope: 字符串\n- constraints: 字符串数组\n- evidence_type: 字符串数组\n- reusability: 只能是 idea_only / adaptable / directly_implementable\n- idea_blocks: 2 到 5 条短句数组\n- transfer_targets: 1 到 5 条数组\n- combination_hooks: 1 到 5 条数组\n- contrast_points: 字符串数组\n- novelty_axes: 字符串数组\n- failure_modes: 1 到 5 条数组，强调研究失效边界\n- followup_questions: 字符串数组\n- source_claim_strength: 只能是 weak / moderate / strong\n- brainstorm_value: 只能是 low / medium / high\n- strategy_type: 字符串数组\n- market: 字符串数组\n- asset_type: 字符串数组\n- holding_period: 字符串\n- summary: 字符串\n- confidence: 0 到 1 的数字\n- entry_rule: 字符串，仅 strategy 可填写\n- exit_rule: 字符串，仅 strategy 可填写\n- rebalance_logic: 字符串，仅 strategy 或 allocation 可填写\n- risk_control: 字符串数组，仅 strategy 可填写\n- backtest_metrics: 对象，仅 strategy 可填写\n\n如果字段无法确定，返回空字符串、空数组或空对象，不要编造。\n\n文章标题：{title}\ncontent_type：{content_type}\n当前 summary：{summary}\n当前 research_question：{research_question}\n当前 core_hypothesis：{core_hypothesis}\n当前 signal_framework：{signal_framework}\n\nMain Content:\n{main_content}\n\nCode Blocks 摘要:\n{code_blocks}\n"""


@dataclass
class EnhancementResult:
    data: dict[str, Any]
    raw_response: str


@dataclass
class ProcessResult:
    article_dir: str
    success: bool
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enhance ingested articles with LLM-generated structured metadata.")
    parser.add_argument("--article-dir", help="Path to a single article directory.")
    parser.add_argument("--articles-root", default=str(DEFAULT_ARTICLES_ROOT), help="Root directory of articles.")
    parser.add_argument("--status-filter", default=DEFAULT_STATUS_FILTER, help="Only process articles with this status.")
    parser.add_argument("--limit", type=int, help="Maximum number of articles to process.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; print enhanced JSON only.")
    parser.add_argument("--force", action="store_true", help="Re-run even if already enriched.")
    parser.add_argument("--concurrency", type=int, default=None, help="Number of concurrent LLM requests (default: LLM_CONCURRENCY env or 3).")
    args = parser.parse_args()
    if args.article_dir and args.limit:
        parser.error("--limit is only valid with --articles-root")
    return args


def get_llm_metadata_config() -> tuple[str, str]:
    """Return (base_url, model) for metadata logging purposes."""
    _, base_url, model = get_llm_config()
    return base_url, model


def discover_article_dirs(args: argparse.Namespace) -> list[Path]:
    if args.article_dir:
        return [Path(args.article_dir).expanduser().resolve()]
    root = Path(args.articles_root).expanduser().resolve()
    dirs = [p for p in root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.name)
    if args.limit:
        dirs = dirs[: args.limit]
    return dirs


def load_article_markdown(article_dir: Path) -> str:
    return (article_dir / "article.md").read_text(encoding="utf-8")


def load_source_json(article_dir: Path) -> dict[str, Any]:
    path = article_dir / "source.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    parts = markdown.split("---\n", 2)
    if len(parts) < 3:
        return {}, markdown
    frontmatter_text = parts[1]
    body = parts[2]
    data: dict[str, Any] = {}
    for line in frontmatter_text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        data[key.strip()] = value.strip()
    return data, body


def should_skip(source_json: dict[str, Any], force: bool) -> bool:
    if force:
        return False
    return bool(source_json.get("llm_enriched"))


def article_matches_status(frontmatter: dict[str, Any], status_filter: str) -> bool:
    return frontmatter.get("status", "") == status_filter


def extract_section(body: str, heading: str) -> str:
    pattern = rf"## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, body, flags=re.S)
    return match.group(1).strip() if match else ""


def truncate_text(text: str, limit: int) -> str:
    return text[:limit]


def build_prompt_payload(frontmatter: dict[str, Any], body: str, source_json: dict[str, Any]) -> dict[str, str]:
    main_content_limit = int(os.getenv("ZHIPU_MAIN_CONTENT_LIMIT", str(DEFAULT_MAIN_CONTENT_LIMIT)))
    code_block_limit = int(os.getenv("ZHIPU_CODE_BLOCK_LIMIT", str(DEFAULT_CODE_BLOCK_LIMIT)))
    code_block_char_limit = int(os.getenv("ZHIPU_CODE_BLOCK_CHAR_LIMIT", str(DEFAULT_CODE_BLOCK_CHAR_LIMIT)))
    main_content = extract_section(body, "Main Content")
    code_blocks = source_json.get("code_blocks", [])
    code_preview = []
    for block in code_blocks[:code_block_limit]:
        language = block.get("language", "text")
        content = truncate_text(block.get("content", ""), code_block_char_limit)
        code_preview.append(f"[{language}]\n{content}")
    return {
        "title": frontmatter.get("title", ""),
        "content_type": frontmatter.get("content_type", ""),
        "summary": frontmatter.get("summary", ""),
        "research_question": frontmatter.get("research_question", ""),
        "core_hypothesis": frontmatter.get("core_hypothesis", ""),
        "signal_framework": frontmatter.get("signal_framework", ""),
        "main_content": truncate_text(main_content, main_content_limit),
        "code_blocks": "\n\n".join(code_preview),
    }


def call_llm_enrich(prompt_payload: dict[str, str]) -> EnhancementResult:
    """Call the LLM to generate structured enrichment for an article."""
    _, _, model = get_llm_config()
    user_prompt = USER_PROMPT_TEMPLATE.format(**prompt_payload)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    data = post_llm_json("/chat/completions", payload)
    raw_text = data["choices"][0]["message"]["content"]
    parsed = parse_json_response(raw_text)
    return EnhancementResult(data=parsed, raw_response=raw_text)


# Backward-compatible alias
call_zhipu_glm = call_llm_enrich


def parse_json_response(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    fenced = re.search(r"```json\s*(\{.*\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def normalize_list(value: Any, max_items: int | None = None) -> list[str]:
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
    elif isinstance(value, str) and value.strip():
        items = [value.strip()]
    else:
        items = []
    if max_items is not None:
        items = items[:max_items]
    return items


def normalize_allowed_list(value: Any, allowed: set[str], max_items: int | None = None) -> list[str]:
    items = normalize_list(value, max_items=max_items)
    return [item for item in items if item in allowed]


def normalize_enum(value: Any, allowed: set[str]) -> str:
    value = str(value).strip()
    return value if value in allowed else ""


def normalize_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def normalize_backtest_metrics(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def validate_enhancement_data(data: dict[str, Any], content_type: str) -> dict[str, Any]:
    normalized = {
        "research_question": str(data.get("research_question", "")).strip(),
        "core_hypothesis": str(data.get("core_hypothesis", "")).strip(),
        "signal_framework": str(data.get("signal_framework", "")).strip(),
        "application_scope": str(data.get("application_scope", "")).strip(),
        "constraints": normalize_list(data.get("constraints")),
        "evidence_type": normalize_list(data.get("evidence_type")),
        "reusability": normalize_enum(data.get("reusability", ""), ALLOWED_REUSABILITY),
        "idea_blocks": normalize_list(data.get("idea_blocks"), max_items=5)[:5],
        "transfer_targets": normalize_list(data.get("transfer_targets"), max_items=5),
        "combination_hooks": normalize_list(data.get("combination_hooks"), max_items=5),
        "contrast_points": normalize_list(data.get("contrast_points")),
        "novelty_axes": normalize_list(data.get("novelty_axes")),
        "failure_modes": normalize_list(data.get("failure_modes"), max_items=5),
        "followup_questions": normalize_list(data.get("followup_questions")),
        "source_claim_strength": normalize_enum(data.get("source_claim_strength", ""), ALLOWED_CLAIM_STRENGTH),
        "brainstorm_value": normalize_enum(data.get("brainstorm_value", ""), ALLOWED_BRAINSTORM_VALUE),
        "strategy_type": normalize_allowed_list(data.get("strategy_type"), ALLOWED_STRATEGY_TYPES),
        "market": normalize_allowed_list(data.get("market"), ALLOWED_MARKETS),
        "asset_type": normalize_allowed_list(data.get("asset_type"), ALLOWED_ASSET_TYPES),
        "holding_period": str(data.get("holding_period", "")).strip(),
        "summary": str(data.get("summary", "")).strip(),
        "confidence": normalize_confidence(data.get("confidence", 0.0)),
        "entry_rule": str(data.get("entry_rule", "")).strip(),
        "exit_rule": str(data.get("exit_rule", "")).strip(),
        "rebalance_logic": str(data.get("rebalance_logic", "")).strip(),
        "risk_control": normalize_list(data.get("risk_control")),
        "backtest_metrics": normalize_backtest_metrics(data.get("backtest_metrics", {})),
    }
    if content_type not in ALLOWED_CONTENT_TYPES:
        content_type = "methodology"
    if content_type != "strategy":
        normalized["entry_rule"] = ""
        normalized["exit_rule"] = ""
        normalized["risk_control"] = []
        normalized["backtest_metrics"] = {}
        if content_type != "allocation":
            normalized["rebalance_logic"] = ""
    if len(normalized["idea_blocks"]) < 2:
        normalized["idea_blocks"] = normalized["idea_blocks"][:]
    return normalized


def format_yaml_value(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        return str(value)
    return str(value)


def update_frontmatter(markdown: str, enhancement: dict[str, Any]) -> str:
    lines = markdown.splitlines()
    in_frontmatter = False
    updated: list[str] = []
    for line in lines:
        if line.strip() == "---":
            updated.append(line)
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            key, sep, _ = line.partition(":")
            if sep and key in enhancement:
                updated.append(f"{key}: {format_yaml_value(enhancement[key])}")
                continue
        updated.append(line)
    return "\n".join(updated)


def replace_section(markdown: str, heading: str, content: str) -> str:
    pattern = rf"(## {re.escape(heading)}\n\n)(.*?)(?=\n## |\Z)"
    replacement = rf"\1{content.strip() if content.strip() else '待补充。'}\n"
    return re.sub(pattern, replacement, markdown, flags=re.S)


def list_to_bullets(items: list[str], empty_text: str = "待补充。") -> str:
    if not items:
        return empty_text
    return "\n".join(f"- {item}" for item in items)


def apply_markdown_updates(markdown: str, enhancement: dict[str, Any], content_type: str) -> str:
    markdown = update_frontmatter(markdown, enhancement)
    markdown = replace_section(markdown, "Summary", enhancement.get("summary", ""))
    markdown = replace_section(markdown, "Research Question", enhancement.get("research_question", ""))
    markdown = replace_section(markdown, "Core Hypothesis", enhancement.get("core_hypothesis", ""))
    markdown = replace_section(markdown, "Application Scope", enhancement.get("application_scope", ""))
    markdown = replace_section(markdown, "Constraints", list_to_bullets(enhancement.get("constraints", [])))
    markdown = replace_section(markdown, "Idea Blocks", list_to_bullets(enhancement.get("idea_blocks", [])))
    markdown = replace_section(markdown, "Combination Hooks", list_to_bullets(enhancement.get("combination_hooks", [])))
    markdown = replace_section(markdown, "Transfer Targets", list_to_bullets(enhancement.get("transfer_targets", [])))
    markdown = replace_section(markdown, "Contrast Points", list_to_bullets(enhancement.get("contrast_points", [])))
    markdown = replace_section(markdown, "Failure Modes", list_to_bullets(enhancement.get("failure_modes", [])))
    markdown = replace_section(markdown, "Follow-up Questions", list_to_bullets(enhancement.get("followup_questions", [])))
    if content_type == "strategy":
        markdown = replace_section(markdown, "Signal / Feature Definition", enhancement.get("signal_framework", ""))
        markdown = replace_section(markdown, "Entry Rule", enhancement.get("entry_rule", ""))
        markdown = replace_section(markdown, "Exit Rule", enhancement.get("exit_rule", ""))
        markdown = replace_section(markdown, "Rebalance / Holding Logic", enhancement.get("rebalance_logic", ""))
        markdown = replace_section(markdown, "Risk Control", list_to_bullets(enhancement.get("risk_control", [])))
        backtest = enhancement.get("backtest_metrics", {})
        markdown = replace_section(markdown, "Backtest Metrics", json.dumps(backtest, ensure_ascii=False, indent=2) if backtest else "待补充。")
    else:
        markdown = replace_section(markdown, "Signal Framework / Decision Framework", enhancement.get("signal_framework", ""))
    return markdown


def update_source_json(source_json: dict[str, Any], enhancement: dict[str, Any], raw_response: str) -> dict[str, Any]:
    base_url, model = get_llm_metadata_config()
    updated = dict(source_json)
    updated.update(enhancement)
    updated["llm_provider"] = base_url
    updated["llm_model"] = model
    updated["llm_base_url"] = base_url
    updated["llm_enriched"] = True
    updated["llm_enriched_at"] = datetime.now().isoformat(timespec="seconds")
    updated["llm_error"] = ""
    updated["llm_raw_response"] = raw_response
    return updated


def mark_source_json_error(source_json: dict[str, Any], error: str) -> dict[str, Any]:
    base_url, _ = get_llm_metadata_config()
    updated = dict(source_json)
    updated["llm_provider"] = base_url
    updated["llm_enriched"] = False
    updated["llm_error"] = error
    updated["llm_enriched_at"] = datetime.now().isoformat(timespec="seconds")
    return updated


def classify_llm_error(error: str) -> str:
    lowered = error.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "json" in lowered:
        return "json_parse_error"
    if "401" in lowered or "403" in lowered or "404" in lowered or "500" in lowered:
        return "api_error"
    if "httpsconnectionpool" in lowered or "request" in lowered:
        return "api_error"
    return "other"


def write_llm_failures(results: list[ProcessResult]) -> Path:
    SOURCES_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{result.article_dir}\t{classify_llm_error(result.error)}\t{result.error}"
        for result in results
        if not result.success
    ]
    LLM_FAILURES_PATH.write_text("\n".join(lines), encoding="utf-8")
    return LLM_FAILURES_PATH


def write_article_dir(article_dir: Path, markdown: str, source_json: dict[str, Any]) -> None:
    (article_dir / "article.md").write_text(markdown, encoding="utf-8")
    (article_dir / "source.json").write_text(json.dumps(source_json, ensure_ascii=False, indent=2), encoding="utf-8")


def process_article_dir(article_dir: Path, args: argparse.Namespace) -> ProcessResult:
    markdown = load_article_markdown(article_dir)
    frontmatter, body = parse_frontmatter(markdown)
    source_json = load_source_json(article_dir)
    if not article_matches_status(frontmatter, args.status_filter):
        return ProcessResult(article_dir=str(article_dir), success=True)
    if should_skip(source_json, args.force):
        return ProcessResult(article_dir=str(article_dir), success=True)

    prompt_payload = build_prompt_payload(frontmatter, body, source_json)
    try:
        enhancement_result = call_llm_enrich(prompt_payload)
        enhancement = validate_enhancement_data(enhancement_result.data, frontmatter.get("content_type", ""))
        if args.dry_run:
            print(json.dumps({"article_dir": str(article_dir), "enhancement": enhancement}, ensure_ascii=False, indent=2))
            return ProcessResult(article_dir=str(article_dir), success=True)
        updated_markdown = apply_markdown_updates(markdown, enhancement, frontmatter.get("content_type", ""))
        updated_source = update_source_json(source_json, enhancement, enhancement_result.raw_response)
        write_article_dir(article_dir, updated_markdown, updated_source)
        return ProcessResult(article_dir=str(article_dir), success=True)
    except LLMAuthError:
        raise  # propagate auth errors for fail-fast handling
    except Exception as exc:
        updated_source = mark_source_json_error(source_json, str(exc))
        if not args.dry_run:
            (article_dir / "source.json").write_text(json.dumps(updated_source, ensure_ascii=False, indent=2), encoding="utf-8")
        return ProcessResult(article_dir=str(article_dir), success=False, error=str(exc))


def get_concurrency(args: argparse.Namespace) -> int:
    """Return the concurrency level from args, env, or default."""
    if getattr(args, "concurrency", None):
        return args.concurrency
    env_val = _env_with_fallback("LLM_CONCURRENCY", "ZHIPU_CONCURRENCY", "")
    if env_val:
        return max(1, int(env_val))
    return DEFAULT_LLM_CONCURRENCY


def run_enrich_batch(
    article_dirs: list[Path],
    args: argparse.Namespace,
    concurrency: int = 1,
    progress_callback=None,
) -> list[ProcessResult]:
    """Enrich a batch of articles, optionally concurrently.

    Args:
        article_dirs: directories to process.
        args: CLI/tool arguments namespace.
        concurrency: max parallel LLM requests.
        progress_callback: optional callable(index, total, result) for progress.

    Returns list of ProcessResult. Stops early on LLMAuthError.
    """
    results: list[ProcessResult] = []
    total = len(article_dirs)
    auth_failed = False

    if concurrency <= 1:
        for i, ad in enumerate(article_dirs):
            result = process_article_dir(ad, args)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, total, result)
            if isinstance(result.error, str) and "authentication failed" in result.error.lower():
                auth_failed = True
                break
        return results

    # Concurrent execution
    future_to_idx = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for i, ad in enumerate(article_dirs):
            if auth_failed:
                break
            future = executor.submit(process_article_dir, ad, args)
            future_to_idx[future] = i

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
            except LLMAuthError as exc:
                result = ProcessResult(
                    article_dir=str(article_dirs[idx]), success=False, error=str(exc)
                )
                auth_failed = True
                # Cancel pending futures
                for f in future_to_idx:
                    f.cancel()
            except Exception as exc:
                result = ProcessResult(
                    article_dir=str(article_dirs[idx]), success=False, error=str(exc)
                )
            results.append(result)
            if progress_callback:
                progress_callback(len(results), total, result)
            if auth_failed:
                break

    return results


def main() -> int:
    args = parse_args()
    article_dirs = discover_article_dirs(args)
    concurrency = get_concurrency(args)

    if concurrency > 1 and len(article_dirs) > 1:
        print(f"Processing {len(article_dirs)} articles with concurrency={concurrency}")

    def _progress(i, total, result):
        status = "ok" if result.success else f"failed: {result.error}"
        print(f"[{i}/{total}] {result.article_dir}: {status}")

    results = run_enrich_batch(article_dirs, args, concurrency, progress_callback=_progress)

    failures = [r for r in results if not r.success]
    failure_list_path = write_llm_failures(results)
    summary = {
        "total": len(results),
        "success": len(results) - len(failures),
        "failed": len(failures),
        "failure_list_path": str(failure_list_path),
        "failed_articles": [
            {"article_dir": r.article_dir, "error": r.error, "error_type": classify_llm_error(r.error)}
            for r in failures
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
