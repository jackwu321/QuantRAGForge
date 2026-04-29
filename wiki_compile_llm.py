from __future__ import annotations

import json
import re
from dataclasses import dataclass

from kb_shared import call_llm_chat


@dataclass
class ProposedConcept:
    slug: str
    title: str
    aliases: list[str]
    rationale: str
    draft_synthesis: str


@dataclass
class ConceptAssignment:
    existing_concepts: list[str]
    proposed_new_concepts: list[ProposedConcept]


_ASSIGN_SYSTEM = """你是知识库概念分类助手。
你的任务是将一篇文章映射到现有概念列表，或在没有匹配时提出最多1个新概念。
输出严格 JSON，不要使用 markdown 代码块包装。"""


def _build_assign_prompt(article_fm: dict, index_text: str) -> str:
    title = article_fm.get("title", "")
    ct = article_fm.get("content_type", "")
    summary = article_fm.get("summary", "") or article_fm.get("core_hypothesis", "")
    ideas = article_fm.get("idea_blocks", [])
    if not isinstance(ideas, list):
        ideas = [str(ideas)]
    idea_text = "\n".join(f"- {i}" for i in ideas[:5])

    return f"""现有概念清单:
{index_text or '(空)'}

待分类文章:
title: {title}
content_type: {ct}
summary: {summary}
idea_blocks:
{idea_text or '(无)'}

输出 JSON schema:
{{
  "existing_concepts": ["<slug>", ...],
  "proposed_new_concepts": [
    {{
      "slug": "<kebab-case-slug>",
      "title": "<Title Case>",
      "aliases": ["<alias>", ...],
      "rationale": "<为什么需要新概念>",
      "draft_synthesis": "<1-2句话的概念定义>"
    }}
  ]
}}

规则:
- 优先匹配现有概念，最多列出 3 个
- 仅当没有合适现有概念且本文有独特视角时才提议新概念，最多 1 个
- proposed_new_concepts 的 slug 使用 kebab-case ASCII"""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = text.rsplit("```", 1)[0]
    return text.strip()


def assign_concepts(article_frontmatter: dict, index_text: str) -> ConceptAssignment:
    prompt = _build_assign_prompt(article_frontmatter, index_text)
    messages = [
        {"role": "system", "content": _ASSIGN_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    try:
        raw = call_llm_chat(messages, temperature=0.1)
    except Exception:
        return ConceptAssignment(existing_concepts=[], proposed_new_concepts=[])

    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        return ConceptAssignment(existing_concepts=[], proposed_new_concepts=[])

    existing = [str(s) for s in data.get("existing_concepts", []) if s]
    proposed = []
    for p in data.get("proposed_new_concepts", []):
        if not isinstance(p, dict):
            continue
        slug = str(p.get("slug", "")).strip()
        if not slug:
            continue
        proposed.append(ProposedConcept(
            slug=slug,
            title=str(p.get("title", slug)),
            aliases=[str(a) for a in p.get("aliases", []) if a],
            rationale=str(p.get("rationale", "")),
            draft_synthesis=str(p.get("draft_synthesis", "")),
        ))
    return ConceptAssignment(existing_concepts=existing, proposed_new_concepts=proposed)


@dataclass
class RecompileResult:
    synthesis: str
    definition: str
    key_idea_blocks: list[str]
    variants: list[str]
    common_combinations: list[str]
    transfer_targets: list[str]
    failure_modes: list[str]
    open_questions: list[str]
    related_concepts: list[str]


_RECOMPILE_SYSTEM = """你是量化投研知识库的概念合成助手。
你的任务是基于多篇来源文章合成一篇概念文章的各个章节。
输出严格 JSON，每个字段独立。Synthesis 是 1-3 段叙事，其它是项目列表。"""


def _format_source_articles(sources: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sources, 1):
        title = s.get("title", "")
        ct = s.get("content_type", "")
        ideas = s.get("idea_blocks", [])
        if not isinstance(ideas, list):
            ideas = [str(ideas)]
        ideas_text = "\n  ".join(f"- {x}" for x in ideas[:5])
        parts.append(f"[Source {i}] {title} ({ct})\n  {ideas_text}")
    return "\n\n".join(parts) or "(no sources)"


def recompile_concept(
    concept_slug: str,
    concept_title: str,
    source_articles: list[dict],
) -> RecompileResult:
    user_prompt = f"""概念 slug: {concept_slug}
概念 title: {concept_title}

来源文章列表:
{_format_source_articles(source_articles)}

输出 JSON schema:
{{
  "synthesis": "<1-3 段，描述这些来源对该概念合起来说了什么>",
  "definition": "<1 段经典定义>",
  "key_idea_blocks": ["<由源文章 idea_blocks 聚合后去重>", ...],
  "variants": ["<不同来源的实现/变体>", ...],
  "common_combinations": ["<可与之组合的概念，使用 [[slug]] 格式>", ...],
  "transfer_targets": ["<可迁移到的市场/资产/周期>", ...],
  "failure_modes": ["<研究失效边界，不要写风控规则>", ...],
  "open_questions": ["<延伸研究问题>", ...],
  "related_concepts": ["<相关概念 slug，无 [[]]>", ...]
}}"""
    messages = [
        {"role": "system", "content": _RECOMPILE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    try:
        raw = call_llm_chat(messages, temperature=0.2)
    except Exception:
        return RecompileResult("", "", [], [], [], [], [], [], [])

    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        return RecompileResult("", "", [], [], [], [], [], [], [])

    def _list(key: str) -> list[str]:
        v = data.get(key, [])
        return [str(x) for x in v] if isinstance(v, list) else []

    return RecompileResult(
        synthesis=str(data.get("synthesis", "")),
        definition=str(data.get("definition", "")),
        key_idea_blocks=_list("key_idea_blocks"),
        variants=_list("variants"),
        common_combinations=_list("common_combinations"),
        transfer_targets=_list("transfer_targets"),
        failure_modes=_list("failure_modes"),
        open_questions=_list("open_questions"),
        related_concepts=_list("related_concepts"),
    )
