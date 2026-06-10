"""Filesystem skill registry for the agent.

Skills are SOP markdown files with YAML frontmatter. Two sources, merged:

1. Package built-ins: ``quant_llm_wiki/agent/skills/*.md`` (read via
   importlib.resources so zip-installed wheels work; body is cached into
   the registry at load time and never re-read from disk).
2. KB-level: ``<kb_root>/.qlw/skills/*.md`` — optional, overrides a
   package skill with the same name.

Pure functions (`load_skill_registry`, `get_skill`) carry the logic; the
``@tool`` wrappers at the bottom are thin LangChain wiring. This module
must not import from .tools (circular dependency).
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from quant_llm_wiki.paths import resolve_kb_root

_SKILLS_PACKAGE = "quant_llm_wiki.agent"
_SKILLS_DIR = "skills"
_KB_SKILLS_SUBDIR = ".qlw/skills"

_REQUIRED_FIELDS = ("name", "description", "triggers", "requires_user_decision", "tools_used")


def _parse_skill_file(text: str, *, path: str, stem: str) -> dict[str, Any] | str:
    """Parse one skill file. Returns the entry dict, or an error string."""
    if not text.startswith("---"):
        return "missing frontmatter"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "missing frontmatter terminator"
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        return f"YAML parse error: {exc}"
    if not isinstance(fm, dict):
        return "frontmatter is not a mapping"

    for field in _REQUIRED_FIELDS:
        if field not in fm:
            return f"missing required field: {field}"

    name = fm["name"]
    if not isinstance(name, str) or not name:
        return "name must be a non-empty string"
    if name != stem:
        return f"frontmatter name '{name}' does not match filename '{stem}.md'"
    if not isinstance(fm["description"], str) or not fm["description"]:
        return "description must be a non-empty string"
    triggers = fm["triggers"]
    if not isinstance(triggers, list) or not triggers or not all(isinstance(t, str) for t in triggers):
        return "triggers must be a non-empty list of strings"
    if not isinstance(fm["requires_user_decision"], bool):
        return "requires_user_decision must be a boolean (true/false, not a string)"
    tools_used = fm["tools_used"]
    if not isinstance(tools_used, list) or not all(isinstance(t, str) for t in tools_used):
        return "tools_used must be a list of strings"

    return {
        "name": name,
        "description": fm["description"],
        "triggers": triggers,
        "requires_user_decision": fm["requires_user_decision"],
        "tools_used": tools_used,
        "version": fm.get("version"),
        "path": path,
        "body": parts[2].lstrip("\n"),
    }


def _load_package_skills(errors: list[dict]) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    skills_dir = resources.files(_SKILLS_PACKAGE).joinpath(_SKILLS_DIR)
    if not skills_dir.is_dir():
        return entries
    for res in sorted(skills_dir.iterdir(), key=lambda r: r.name):
        if not res.name.endswith(".md"):
            continue
        path = f"package:{res.name}"
        try:
            text = res.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)})
            continue
        entry = _parse_skill_file(text, path=path, stem=res.name[: -len(".md")])
        if isinstance(entry, str):
            errors.append({"path": path, "error": entry})
            continue
        entry["source"] = "package"
        entry["overrides"] = None
        entries[entry["name"]] = entry
    return entries


def _load_kb_skills(kb_root: Path, package_entries: dict[str, dict], errors: list[dict]) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    kb_dir = kb_root / _KB_SKILLS_SUBDIR
    if not kb_dir.is_dir():
        return entries
    for f in sorted(kb_dir.glob("*.md")):
        path = str(f)
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)})
            continue
        entry = _parse_skill_file(text, path=path, stem=f.stem)
        if isinstance(entry, str):
            errors.append({"path": path, "error": entry})
            continue
        entry["source"] = "kb"
        overridden = package_entries.get(entry["name"])
        entry["overrides"] = overridden["path"] if overridden else None
        entries[entry["name"]] = entry
    return entries


def _load_all(kb_root: Path | None = None) -> tuple[dict[str, dict], list[dict]]:
    """Merged registry (KB overrides package), entries include body."""
    root = kb_root if kb_root is not None else resolve_kb_root(None)
    errors: list[dict] = []
    merged = _load_package_skills(errors)
    merged.update(_load_kb_skills(root, merged, errors))
    return merged, errors


def load_skill_registry(kb_root: Path | None = None) -> dict:
    """Final effective registry: overridden package versions are omitted."""
    merged, errors = _load_all(kb_root)
    skills = [{k: v for k, v in entry.items() if k != "body"} for entry in merged.values()]
    return {"skills": skills, "_errors": errors}


def get_skill(name: str, kb_root: Path | None = None) -> dict:
    """Full SOP for one skill. Lookup is by registry key only — the name is
    never joined into a filesystem path, so traversal-style names
    (``../x``, absolute paths, ``foo.md``) all fall into skill_not_found."""
    merged, _ = _load_all(kb_root)
    entry = merged.get(name)
    if entry is None:
        return {"error": "skill_not_found", "name": name, "available": sorted(merged)}
    frontmatter = {
        k: entry[k]
        for k in ("description", "triggers", "requires_user_decision", "tools_used", "version")
    }
    return {
        "name": entry["name"],
        "source": entry["source"],
        "path": entry["path"],
        "frontmatter": frontmatter,
        "body": entry["body"],
    }


# ---------------------------------------------------------------------------
# LangChain @tool wrappers
#
# These return JSON *strings*, not dicts: GLM-4.7 (the default agent model)
# reproducibly emits an empty final answer after receiving a dict-typed
# ToolMessage, and every other tool in tools.py already returns str.
# ---------------------------------------------------------------------------

import json  # noqa: E402

from langchain_core.tools import tool  # noqa: E402


@tool
def list_skills() -> str:
    """List all registered skills (multi-step SOPs).

    Returns name / description / triggers / requires_user_decision /
    tools_used for each skill. Match the user's intent against triggers,
    then call read_skill(name) to get the full SOP."""
    return json.dumps(load_skill_registry(), ensure_ascii=False, indent=2)


@tool
def read_skill(name: str) -> str:
    """Read the full SOP markdown of one skill by name (e.g. 'full-ingest').

    Returns frontmatter plus the step-by-step body. If the name is unknown,
    returns skill_not_found with the list of available skills."""
    return json.dumps(get_skill(name), ensure_ascii=False, indent=2)
