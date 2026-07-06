"""实验判决一等公民：StraMuse 回测判决的结构化存储 + 向量检索层。

判决是机器产生的结构化事实，不走文章 review 流水线（设计 D4）：
StraMuse 跑完回测经 `qlw verdict add` 自动写入，脑暴的批判循环与生成
prompt 都从这里取"已证伪方向"的弹药。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_VERDICTS: tuple[str, ...] = ("成立", "暂不成立", "被证伪", "需要更多数据")
KB_LAYER_VERDICT = "verdict"

_REQUIRED_FIELDS = ("id", "date", "direction", "hypothesis", "verdict")
_OPTIONAL_FIELDS = ("metrics", "universe", "period", "failure_summary", "source_brief")


class VerdictError(ValueError):
    """入参不合规（缺字段/判决级别非法/YAML 不是映射）。"""


@dataclass
class VerdictRecord:
    id: str
    date: str
    direction: str
    hypothesis: str
    verdict: str
    metrics: dict[str, Any] = field(default_factory=dict)
    universe: str = ""
    period: str = ""
    failure_summary: str = ""
    source_brief: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def parse_verdict_data(data: Any) -> VerdictRecord:
    if not isinstance(data, dict):
        raise VerdictError("verdict YAML 顶层必须是键值映射（mapping）")
    missing = [f for f in _REQUIRED_FIELDS if not str(data.get(f, "")).strip()]
    if missing:
        raise VerdictError(f"缺少必填字段：{', '.join(missing)}")
    verdict = str(data["verdict"]).strip()
    if verdict not in VALID_VERDICTS:
        raise VerdictError(
            f"verdict 必须是 {'/'.join(VALID_VERDICTS)} 之一，收到：{verdict}"
        )
    known = set(_REQUIRED_FIELDS) | set(_OPTIONAL_FIELDS)
    extra = {k: v for k, v in data.items() if k not in known}
    metrics = data.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise VerdictError("metrics 必须是键值映射")
    return VerdictRecord(
        id=str(data["id"]).strip(),
        date=str(data["date"]).strip(),
        direction=str(data["direction"]).strip(),
        hypothesis=str(data["hypothesis"]).strip(),
        verdict=verdict,
        metrics=metrics,
        universe=str(data.get("universe", "") or ""),
        period=str(data.get("period", "") or ""),
        failure_summary=str(data.get("failure_summary", "") or ""),
        source_brief=str(data.get("source_brief", "") or ""),
        extra=extra,
    )


def verdicts_dir(kb_root: Path) -> Path:
    return Path(kb_root) / "verdicts"


def _record_to_data(record: VerdictRecord) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": record.id,
        "date": record.date,
        "direction": record.direction,
        "hypothesis": record.hypothesis,
        "verdict": record.verdict,
    }
    if record.metrics:
        data["metrics"] = record.metrics
    for name in ("universe", "period", "failure_summary", "source_brief"):
        value = getattr(record, name)
        if value:
            data[name] = value
    data.update(record.extra)
    return data


def save_verdict(kb_root: Path, record: VerdictRecord) -> Path:
    """同 id 幂等覆盖（重跑回测 = 更新判决，不产生副本）。"""
    from quant_llm_wiki.query.brainstorm import slugify

    out_dir = verdicts_dir(kb_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slugify(record.id)}.yaml"
    path.write_text(
        yaml.safe_dump(_record_to_data(record), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def load_verdict(path: Path) -> VerdictRecord:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise VerdictError(f"verdict 文件不是合法 YAML：{exc}") from exc
    return parse_verdict_data(data)


def list_verdicts(kb_root: Path, verdict: str | None = None) -> list[VerdictRecord]:
    vdir = verdicts_dir(kb_root)
    if not vdir.exists():
        return []
    records: list[VerdictRecord] = []
    for p in sorted(vdir.glob("*.yaml")):
        try:
            records.append(load_verdict(p))
        except VerdictError:
            continue  # 坏文件跳过，不让单个坏判决拖垮整层
    if verdict:
        records = [r for r in records if r.verdict == verdict]
    records.sort(key=lambda r: r.date, reverse=True)
    return records


def verdict_embed_text(record: VerdictRecord) -> str:
    """嵌入文本 = direction + hypothesis + 判决 + failure_summary（spec 第 3 节）。"""
    parts = [record.direction, record.hypothesis, f"判决：{record.verdict}"]
    if record.failure_summary:
        parts.append(f"失败原因：{record.failure_summary}")
    return "\n".join(parts)
