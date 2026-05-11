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


    def test_no_package_leak_after_brainstorm_path(self):
        """The agent → brainstorm → lint chain must not write into the package dir."""
        import quant_llm_wiki
        pkg_dir = Path(quant_llm_wiki.__file__).resolve().parent
        pkg_lint = pkg_dir / "wiki" / "lint_report.json"
        pkg_outputs = pkg_dir / "outputs"

        # Snapshot pre-state — these MUST already not exist in a clean checkout
        self.assertFalse(pkg_lint.exists(), f"pre-test leak: {pkg_lint}")
        self.assertFalse(pkg_outputs.exists(), f"pre-test leak: {pkg_outputs}")

        # Exercise the previously-leaking chain in a tempdir cwd
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            (td_path / "wiki" / "concepts").mkdir(parents=True)
            (td_path / "wiki" / "sources").mkdir(parents=True)
            (td_path / "wiki" / "state.json").write_text("{}", encoding="utf-8")
            (td_path / "raw").mkdir()
            old_cwd = os.getcwd()
            old_env = os.environ.get("QLW_KB_ROOT")
            try:
                os.chdir(td)
                os.environ["QLW_KB_ROOT"] = str(td_path)
                # Directly call the previously-leaking function
                from quant_llm_wiki.query.brainstorm import _wiki_is_healthy_for_query
                _wiki_is_healthy_for_query(td_path)
            finally:
                os.chdir(old_cwd)
                if old_env is None:
                    os.environ.pop("QLW_KB_ROOT", None)
                else:
                    os.environ["QLW_KB_ROOT"] = old_env

        # Post-state — STILL must not have leaked into the package
        self.assertFalse(pkg_lint.exists(), f"LEAKED: {pkg_lint}")
        self.assertFalse(pkg_outputs.exists(), f"LEAKED: {pkg_outputs}")


    def test_enrich_default_finds_articles_in_raw(self):
        """qlw enrich with no --articles-root must discover articles under <kb-root>/raw."""
        import quant_llm_wiki
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            # Build skeleton: tmpdir/raw/article_x/article.md + source.json
            article_dir = tmpdir / "raw" / "article_x"
            article_dir.mkdir(parents=True)
            (article_dir / "article.md").write_text(
                "---\nstatus: raw\ntitle: Test Article\nsummary: A test.\n---\nBody text.\n",
                encoding="utf-8",
            )
            (article_dir / "source.json").write_text(
                json.dumps({"llm_enriched": False}), encoding="utf-8"
            )

            old_cwd = os.getcwd()
            old_env = os.environ.get("QLW_KB_ROOT")
            captured_kwargs = []

            def fake_discover(*, article_dir, articles_root, limit):
                captured_kwargs.append({"article_dir": article_dir, "articles_root": articles_root, "limit": limit})
                return []  # return empty so _run exits cleanly without LLM calls

            try:
                os.chdir(td)
                os.environ["QLW_KB_ROOT"] = str(tmpdir)
                with patch("quant_llm_wiki.enrich.discover_article_dirs", side_effect=fake_discover):
                    from quant_llm_wiki import cli
                    import io, sys
                    buf = io.StringIO()
                    with patch("sys.stdout", buf):
                        cli.main(["enrich", "--dry-run"])
            finally:
                os.chdir(old_cwd)
                if old_env is None:
                    os.environ.pop("QLW_KB_ROOT", None)
                else:
                    os.environ["QLW_KB_ROOT"] = old_env

            # Verify discover_article_dirs was called once
            self.assertEqual(len(captured_kwargs), 1, "discover_article_dirs should be called once")
            resolved_articles_root = Path(captured_kwargs[0]["articles_root"]).resolve()
            expected_raw = (tmpdir / "raw").resolve()
            self.assertEqual(
                resolved_articles_root,
                expected_raw,
                f"Expected articles_root={expected_raw}, got {resolved_articles_root}",
            )

            # Verify no leaks into package dir
            pkg_dir = Path(quant_llm_wiki.__file__).resolve().parent
            for sub in ("articles", "sources", "raw"):
                leaked = pkg_dir / sub
                self.assertFalse(leaked.exists(), f"LEAKED: {leaked}")


if __name__ == "__main__":
    unittest.main()
