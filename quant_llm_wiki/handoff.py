"""通用 handoff schema 机制（设计 D5）：KB 配置注入一份 JSON Schema，
收敛落盘时同时产出按该 schema 校验的 yaml。qlw 对 schema 内容零假设——
任何下游工具（回测引擎、执行系统等）把自己的 schema 放进 .qlw/ 即启用。
jsonschema 只做结构校验；字段语义（如 qlib 表达式正确性）由下游兜底。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import yaml

from quant_llm_wiki.shared import call_llm_chat

MAX_ATTEMPTS = 3  # 1 次生成 + 2 次自修

HANDOFF_SYSTEM_PROMPT = """你是策略简报的结构化转换器。把给定简报内容转成一份 YAML，
字段与格式严格遵循给定 JSON Schema（含每个字段 description 里的书写指引）。
规则：
- 只输出 YAML，不要解释、不要 markdown 代码块
- 简报里没有的信息不许编造；schema 允许为空的字段留空
- 不改变简报的想法本身"""


class HandoffError(RuntimeError):
    """handoff yaml 产出失败（加载坏 schema / 自修 2 次仍不过校验）。"""


def handoff_schema_path(kb_root: Path) -> Path:
    return Path(kb_root) / ".qlw" / "handoff_schema.json"


def load_handoff_schema(kb_root: Path) -> dict | None:
    path = handoff_schema_path(kb_root)
    if not path.exists():
        return None
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError(f"handoff schema 不可读：{exc}") from exc
    if not isinstance(schema, dict):
        raise HandoffError("handoff schema 顶层必须是 JSON object")
    return schema


def _strip_fence(text: str) -> str:
    m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1) if m else text


def render_handoff_yaml(
    topic: str,
    content: str,
    schema: dict,
    llm: Callable[[list[dict]], str] | None = None,
) -> str:
    import jsonschema

    llm = llm or call_llm_chat
    base_user = (f"JSON Schema：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
                 f"简报标题：{topic}\n简报内容：\n---\n{content}\n---")
    last_err = ""
    for attempt in range(MAX_ATTEMPTS):
        user = base_user if attempt == 0 else (
            base_user + f"\n\n你上一次的输出未通过校验：\n{last_err}\n请修正后重新输出完整 YAML。")
        raw = _strip_fence(llm([
            {"role": "system", "content": HANDOFF_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]))
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            last_err = f"不是合法 YAML：{exc}"
            continue
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as exc:
            last_err = exc.message
            continue
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    raise HandoffError(f"自修 {MAX_ATTEMPTS - 1} 次后仍未通过 schema 校验：{last_err}")
