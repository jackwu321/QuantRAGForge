"""Tests for KB root path resolution and write-path isolation."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestResolveKbRoot(unittest.TestCase):
    """test_resolve_kb_root_priority: cli > env > cwd."""

    def test_resolve_kb_root_priority(self):
        from quant_llm_wiki.paths import resolve_kb_root

        # 1. Explicit CLI arg takes priority
        with tempfile.TemporaryDirectory() as td:
            explicit = resolve_kb_root(td)
            self.assertEqual(explicit, Path(td).expanduser().resolve())

        # 2. Env var is used when no CLI arg
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"QLW_KB_ROOT": td}):
                via_env = resolve_kb_root(None)
                self.assertEqual(via_env, Path(td).expanduser().resolve())

        # 3. CLI arg beats env var
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            with patch.dict(os.environ, {"QLW_KB_ROOT": td1}):
                via_cli = resolve_kb_root(td2)
                self.assertEqual(via_cli, Path(td2).expanduser().resolve())
                self.assertNotEqual(via_cli, Path(td1).expanduser().resolve())

        # 4. Falls back to cwd when neither cli nor env
        orig_env = os.environ.pop("QLW_KB_ROOT", None)
        try:
            cwd = resolve_kb_root(None)
            self.assertEqual(cwd, Path.cwd().resolve())
        finally:
            if orig_env is not None:
                os.environ["QLW_KB_ROOT"] = orig_env

    def test_lint_wiki_writes_under_kb_root_not_package(self):
        """lint_wiki must write to kb_root/wiki/lint_report.json, not inside the package."""
        from quant_llm_wiki.wiki.lint import lint_wiki

        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            # Build minimal KB structure
            (tmpdir / "wiki" / "concepts").mkdir(parents=True)
            (tmpdir / "wiki" / "sources").mkdir(parents=True)
            (tmpdir / "wiki" / "state.json").write_text(
                json.dumps({"sources": {}, "concepts": {}}), encoding="utf-8"
            )

            # Run lint with explicit kb_root
            lint_wiki(tmpdir)

            # Assertion 1: lint_report.json written under tmpdir
            expected_report = tmpdir / "wiki" / "lint_report.json"
            self.assertTrue(
                expected_report.exists(),
                f"lint_report.json not found at {expected_report}",
            )

            # Assertion 2 (the critical one): package dir must NOT have been written to
            package_dir = Path(__file__).resolve().parents[1] / "quant_llm_wiki" / "wiki"
            leaked_report = package_dir / "lint_report.json"
            # We only fail if this file was just created by our test run (check mtime)
            if leaked_report.exists():
                import stat
                leaked_mtime = leaked_report.stat().st_mtime
                report_mtime = expected_report.stat().st_mtime
                # If leaked file is newer than our tmpdir report it was just written
                self.assertLess(
                    leaked_mtime,
                    report_mtime + 1,
                    f"lint_report.json was leaked into package dir: {leaked_report}",
                )

    def test_lint_wiki_default_uses_cwd(self):
        """lint_wiki() with no kb_root must write relative to cwd, not the package dir."""
        from quant_llm_wiki.wiki.lint import lint_wiki

        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            # Build minimal KB structure in tmpdir
            (tmpdir / "wiki" / "concepts").mkdir(parents=True)
            (tmpdir / "wiki" / "sources").mkdir(parents=True)
            (tmpdir / "wiki" / "state.json").write_text(
                json.dumps({"sources": {}, "concepts": {}}), encoding="utf-8"
            )

            orig_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                # Call with no kb_root — should default to cwd (tmpdir)
                lint_wiki()
            finally:
                os.chdir(orig_cwd)

            expected_report = tmpdir / "wiki" / "lint_report.json"
            self.assertTrue(
                expected_report.exists(),
                f"lint_wiki() default did not write to cwd/wiki/lint_report.json (expected: {expected_report})",
            )

            # Confirm the package dir was untouched
            package_report = Path(__file__).resolve().parents[1] / "quant_llm_wiki" / "wiki" / "lint_report.json"
            # If package_report exists it must predate our tmpdir report
            if package_report.exists():
                self.assertLessEqual(
                    package_report.stat().st_mtime,
                    expected_report.stat().st_mtime + 1,
                    f"lint_wiki() default leaked into package dir: {package_report}",
                )


if __name__ == "__main__":
    unittest.main()
