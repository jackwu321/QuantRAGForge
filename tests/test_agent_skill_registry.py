from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_llm_wiki.agent.skill_registry import (  # noqa: E402
    get_skill,
    list_skills,
    load_skill_registry,
    read_skill,
)

CORE_SKILLS = ["concept-review", "full-ingest", "kb-health-check", "wiki-explanation"]

VALID_KB_SKILL = textwrap.dedent("""\
    ---
    name: {name}
    description: KB-level skill for testing
    version: 7
    triggers:
      - kb test
    requires_user_decision: false
    tools_used:
      - list_articles
    ---

    ## Steps
    1. KB body marker
    """)


@pytest.fixture(autouse=True)
def isolated_kb_root(tmp_path, monkeypatch):
    """Never resolve to the developer's real KB / .qlw/skills."""
    monkeypatch.setenv("QLW_KB_ROOT", str(tmp_path))
    return tmp_path


def write_kb_skill(kb_root: Path, name: str, content: str | None = None) -> Path:
    skills_dir = kb_root / ".qlw" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{name}.md"
    path.write_text(content if content is not None else VALID_KB_SKILL.format(name=name), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. Loader behavior
# ---------------------------------------------------------------------------


class TestLoader:
    def test_package_skills_load(self, tmp_path):
        reg = load_skill_registry(tmp_path)
        names = sorted(s["name"] for s in reg["skills"])
        assert names == CORE_SKILLS
        assert reg["_errors"] == []
        assert all(s["source"] == "package" for s in reg["skills"])
        assert all(s["overrides"] is None for s in reg["skills"])

    def test_missing_kb_skills_dir_is_skipped(self, tmp_path):
        assert not (tmp_path / ".qlw").exists()
        reg = load_skill_registry(tmp_path)
        assert len(reg["skills"]) == 4
        assert reg["_errors"] == []

    def test_kb_overrides_package_by_name(self, tmp_path):
        write_kb_skill(tmp_path, "full-ingest")
        reg = load_skill_registry(tmp_path)
        entries = {s["name"]: s for s in reg["skills"]}
        assert len(reg["skills"]) == 4  # overridden package version not duplicated
        fi = entries["full-ingest"]
        assert fi["source"] == "kb"
        assert fi["overrides"] == "package:full-ingest.md"
        assert fi["version"] == 7

    def test_kb_only_skill_discovered(self, tmp_path):
        write_kb_skill(tmp_path, "my-custom-flow")
        reg = load_skill_registry(tmp_path)
        entries = {s["name"]: s for s in reg["skills"]}
        assert "my-custom-flow" in entries
        assert entries["my-custom-flow"]["source"] == "kb"
        assert entries["my-custom-flow"]["overrides"] is None

    def test_kb_override_body_actually_served(self, tmp_path):
        write_kb_skill(tmp_path, "full-ingest")
        skill = get_skill("full-ingest", tmp_path)
        assert "KB body marker" in skill["body"]
        assert "enrich_articles" not in skill["body"]
        assert skill["source"] == "kb"


# ---------------------------------------------------------------------------
# 2. Schema validation
# ---------------------------------------------------------------------------


def _kb_skill_with_frontmatter(name: str, fm_lines: str) -> str:
    return f"---\n{fm_lines}\n---\n\nbody\n"


class TestSchemaValidation:
    @pytest.mark.parametrize("missing", ["description", "triggers", "requires_user_decision", "tools_used"])
    def test_missing_required_field_rejected(self, tmp_path, missing):
        fields = {
            "name": "bad-skill",
            "description": "x",
            "triggers": "\ntriggers:\n  - t",
            "requires_user_decision": "false",
            "tools_used": "\ntools_used: []",
        }
        lines = [f"name: {fields['name']}"]
        if missing != "description":
            lines.append(f"description: {fields['description']}")
        if missing != "triggers":
            lines.append("triggers:\n  - t")
        if missing != "requires_user_decision":
            lines.append("requires_user_decision: false")
        if missing != "tools_used":
            lines.append("tools_used: []")
        write_kb_skill(tmp_path, "bad-skill", _kb_skill_with_frontmatter("bad-skill", "\n".join(lines)))
        reg = load_skill_registry(tmp_path)
        assert all(s["name"] != "bad-skill" for s in reg["skills"])
        assert any(missing in e["error"] for e in reg["_errors"])

    def test_empty_triggers_rejected(self, tmp_path):
        fm = "name: bad-skill\ndescription: x\ntriggers: []\nrequires_user_decision: false\ntools_used: []"
        write_kb_skill(tmp_path, "bad-skill", _kb_skill_with_frontmatter("bad-skill", fm))
        reg = load_skill_registry(tmp_path)
        assert any("triggers" in e["error"] for e in reg["_errors"])

    def test_non_string_triggers_rejected(self, tmp_path):
        fm = "name: bad-skill\ndescription: x\ntriggers:\n  - 1\nrequires_user_decision: false\ntools_used: []"
        write_kb_skill(tmp_path, "bad-skill", _kb_skill_with_frontmatter("bad-skill", fm))
        reg = load_skill_registry(tmp_path)
        assert any("triggers" in e["error"] for e in reg["_errors"])

    def test_string_requires_user_decision_rejected(self, tmp_path):
        fm = 'name: bad-skill\ndescription: x\ntriggers:\n  - t\nrequires_user_decision: "true"\ntools_used: []'
        write_kb_skill(tmp_path, "bad-skill", _kb_skill_with_frontmatter("bad-skill", fm))
        reg = load_skill_registry(tmp_path)
        assert any("requires_user_decision" in e["error"] for e in reg["_errors"])

    def test_basename_name_mismatch_rejected(self, tmp_path):
        fm = "name: other-name\ndescription: x\ntriggers:\n  - t\nrequires_user_decision: false\ntools_used: []"
        write_kb_skill(tmp_path, "bad-skill", _kb_skill_with_frontmatter("bad-skill", fm))
        reg = load_skill_registry(tmp_path)
        assert any("does not match filename" in e["error"] for e in reg["_errors"])

    def test_no_frontmatter_rejected(self, tmp_path):
        write_kb_skill(tmp_path, "bad-skill", "just a markdown body, no frontmatter\n")
        reg = load_skill_registry(tmp_path)
        assert any("frontmatter" in e["error"] for e in reg["_errors"])

    def test_broken_yaml_rejected_with_path(self, tmp_path):
        path = write_kb_skill(tmp_path, "bad-skill", "---\nname: [unclosed\n  asdf: :\n---\nbody\n")
        reg = load_skill_registry(tmp_path)
        assert any(e["path"] == str(path) for e in reg["_errors"])


# ---------------------------------------------------------------------------
# 3. Errors do not block valid skills (key regression)
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    def test_bad_file_does_not_block_valid_kb_skill(self, tmp_path):
        write_kb_skill(tmp_path, "good-skill")
        write_kb_skill(tmp_path, "broken-skill", "---\n:::\n---\nbody\n")
        reg = load_skill_registry(tmp_path)
        names = {s["name"] for s in reg["skills"]}
        assert "good-skill" in names
        assert set(CORE_SKILLS) <= names
        assert len(reg["_errors"]) == 1
        assert "broken-skill" in reg["_errors"][0]["path"]


# ---------------------------------------------------------------------------
# 4. read_skill boundaries & security
# ---------------------------------------------------------------------------


class TestReadSkillBoundaries:
    @pytest.mark.parametrize(
        "name",
        ["nope", "../../../etc/passwd", "full-ingest.md", "/abs/path/full-ingest", "", "..\\full-ingest"],
    )
    def test_invalid_names_return_skill_not_found(self, tmp_path, name):
        result = get_skill(name, tmp_path)
        assert result["error"] == "skill_not_found"
        assert result["name"] == name
        assert sorted(result["available"]) == CORE_SKILLS


# ---------------------------------------------------------------------------
# 5. Core skill content sanity
# ---------------------------------------------------------------------------


class TestCoreSkillSanity:
    @pytest.mark.parametrize("name", CORE_SKILLS)
    def test_tools_used_all_exist(self, tmp_path, name):
        from quant_llm_wiki.agent.tools import ALL_TOOLS

        tool_names = {t.name for t in ALL_TOOLS}
        skill = get_skill(name, tmp_path)
        assert set(skill["frontmatter"]["tools_used"]) <= tool_names

    @pytest.mark.parametrize("name", CORE_SKILLS)
    def test_pause_marker_matches_requires_user_decision(self, tmp_path, name):
        skill = get_skill(name, tmp_path)
        if skill["frontmatter"]["requires_user_decision"]:
            assert "[PAUSE]" in skill["body"]
        else:
            assert "[PAUSE]" not in skill["body"]


# ---------------------------------------------------------------------------
# 6. JSON serialization + tool wrapper wiring smoke
# ---------------------------------------------------------------------------


class TestJsonAndWiring:
    def test_registry_json_serializable(self, tmp_path):
        write_kb_skill(tmp_path, "good-skill")
        write_kb_skill(tmp_path, "broken-skill", "no frontmatter\n")
        json.dumps(load_skill_registry(tmp_path))
        json.dumps(get_skill("full-ingest", tmp_path))
        json.dumps(get_skill("../nope", tmp_path))

    def test_tool_wrapper_wiring(self):
        # QLW_KB_ROOT is monkeypatched by the autouse fixture, so the
        # wrappers' default kb_root resolution stays inside tmp_path.
        reg = list_skills.invoke({})
        assert sorted(s["name"] for s in reg["skills"]) == CORE_SKILLS
        skill = read_skill.invoke({"name": "full-ingest"})
        assert skill["name"] == "full-ingest"
        assert "[PAUSE]" in skill["body"]


# ---------------------------------------------------------------------------
# 7. Regression: agent-level ingest_article must NOT auto compile/embed.
#    The full-ingest skill's steps 5-6 (compile_wiki, embed_knowledge)
#    rely on this; only the CLI path (run_ingest_source) auto-compiles.
# ---------------------------------------------------------------------------


class TestIngestArticleNoAutoCompile:
    def test_ingest_article_does_not_compile_or_embed(self, tmp_path, monkeypatch):
        import quant_llm_wiki.embed as embed_mod
        import quant_llm_wiki.ingest.source as ingest_source
        import quant_llm_wiki.wiki.compile as wiki_compile
        from quant_llm_wiki.agent.tools import ingest_article

        calls: list[str] = []
        monkeypatch.setattr(
            ingest_source, "dispatch_url", lambda url, **kw: str(tmp_path / "raw" / "fake_article")
        )
        monkeypatch.setattr(
            wiki_compile, "compile_wiki", lambda *a, **kw: calls.append("compile_wiki")
        )
        monkeypatch.setattr(embed_mod, "run_embed", lambda *a, **kw: calls.append("run_embed"))

        result = ingest_article.invoke({"url": "https://example.com/article"})

        assert "1 ingested" in result
        assert calls == []
        assert not (tmp_path / "wiki").exists()
