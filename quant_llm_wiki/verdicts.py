"""实验判决一等公民：外部回测/实验结论的结构化存储 + 向量检索层。

判决是机器产生的结构化事实，不走文章 review 流水线（设计 D4）：
任何下游回测工具跑完实验经 `qlw verdict add` 写入（也可手工投递），
脑暴的批判循环与生成 prompt 都从这里取"已证伪方向"的弹药。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quant_llm_wiki.shared import embed_text

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


# ---------------------------------------------------------------------------
# 向量层：kb_layer="verdict"，与文章/wiki 同 collection 不同层
# ---------------------------------------------------------------------------

def _verdict_block_id(record: VerdictRecord) -> str:
    from quant_llm_wiki.query.brainstorm import slugify
    return f"verdict__{slugify(record.id)}"


def embed_verdict(record: VerdictRecord, vector_store_dir: Path) -> None:
    """单条判决即时嵌入（`qlw verdict add` 路径）。失败抛异常，调用方警告。"""
    from quant_llm_wiki.embed import open_collection

    Path(vector_store_dir).mkdir(parents=True, exist_ok=True)
    collection = open_collection(Path(vector_store_dir))
    text = verdict_embed_text(record)
    collection.upsert(
        ids=[_verdict_block_id(record)],
        documents=[text],
        metadatas=[{
            "kb_layer": KB_LAYER_VERDICT,
            "verdict_id": record.id,
            "verdict": record.verdict,
            "date": record.date,
            "direction": record.direction,
        }],
        embeddings=[embed_text(text)],
    )


def embed_all_verdicts(kb_root: Path, vector_store_dir: Path) -> int:
    """全量重建路径（embed_knowledge 收尾调用）。返回成功条数。"""
    count = 0
    for record in list_verdicts(kb_root):
        try:
            embed_verdict(record, vector_store_dir)
            count += 1
        except Exception:
            continue  # 单条失败不拖垮重建；失败条目下次重建再试
    return count


def retrieve_similar_verdicts(
    query_text: str, vector_store_dir: Path, top_k: int = 3
) -> list[dict]:
    """按语义相似度检索判决。任何失败都返回 []（批判步的显式降级路径）。"""
    try:
        from quant_llm_wiki.embed import open_collection

        collection = open_collection(Path(vector_store_dir))
        if collection.count() <= 0:
            return []
        results = collection.query(
            query_embeddings=[embed_text(query_text)],
            n_results=min(top_k * 2, collection.count()),
            where={"kb_layer": {"$eq": KB_LAYER_VERDICT}},
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    hits = [
        {
            "id": str(m.get("verdict_id", "")),
            "verdict": str(m.get("verdict", "")),
            "date": str(m.get("date", "")),
            "direction": str(m.get("direction", "")),
            "text": str(d),
            "score": max(0.0, 1.0 - float(dist)),
        }
        for d, m, dist in zip(docs, metas, dists)
    ]
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]


# ---------------------------------------------------------------------------
# CLI: qlw verdict add|list
# ---------------------------------------------------------------------------

def run_add(source: Path, kb_root: Path, vector_store_dir: Path | None = None) -> int:
    try:
        record = load_verdict(Path(source))
    except (VerdictError, OSError) as exc:
        print(f"error: {exc}")
        return 2
    path = save_verdict(kb_root, record)
    store = vector_store_dir or (Path(kb_root) / "vector_store")
    try:
        embed_verdict(record, store)
        embedded = "embedded"
    except Exception as exc:
        embedded = (f"warning: 嵌入失败（{type(exc).__name__}: {exc}），"
                    "yaml 已落盘；下次 embed_knowledge 重建会补上")
    print(f"verdict saved: {path} ({embedded})")
    return 0


def run_list(kb_root: Path, verdict: str | None) -> int:
    records = list_verdicts(kb_root, verdict=verdict)
    if not records:
        print("no verdicts")
        return 0
    for r in records:
        print(f"{r.date}  {r.verdict:　<6}  {r.id}  {r.direction}")
    return 0


def register(parser) -> None:
    """Attach verdict subcommands. Called by quant_llm_wiki.cli."""
    from quant_llm_wiki.paths import resolve_kb_root

    sub = parser.add_subparsers(dest="verdict_cmd", required=True)
    p_add = sub.add_parser("add", help="校验并写入一条实验判决（幂等，即时嵌入）")
    p_add.add_argument("source", help="判决 YAML 文件路径")
    p_add.add_argument("--kb-root", default=None)
    p_add.set_defaults(func=lambda a: run_add(
        Path(a.source), resolve_kb_root(a.kb_root)))
    p_list = sub.add_parser("list", help="列出实验判决")
    p_list.add_argument("--verdict", default=None,
                        help="按判决级别过滤（成立/暂不成立/被证伪/需要更多数据）")
    p_list.add_argument("--kb-root", default=None)
    p_list.set_defaults(func=lambda a: run_list(
        resolve_kb_root(a.kb_root), a.verdict))
