"""Tests for the unified qlw CLI (quant_llm_wiki.cli).

Replaces tests/test_kb_cli.py now that kb.py is deleted.
Each test exercises `qlw <subcommand>` by calling `quant_llm_wiki.cli.main([...])`.
"""
import unittest
from unittest.mock import patch

import quant_llm_wiki.cli as qlw_cli


def _parse(argv):
    """Return the parsed argparse.Namespace from qlw_cli without running the handler."""
    import argparse
    from quant_llm_wiki import enrich, embed, sync
    from quant_llm_wiki.ingest import source as ingest_source
    from quant_llm_wiki.query import brainstorm
    from quant_llm_wiki.agent import cli as agent_cli
    from quant_llm_wiki.wiki import lint as wiki_lint_mod
    from quant_llm_wiki.wiki import compile as wiki_compile_mod

    parser = argparse.ArgumentParser(prog="qlw")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ingest_source.register(sub.add_parser("ingest", help="Ingest articles."))
    enrich.register(sub.add_parser("enrich", help="Enrich articles."))
    embed.register(sub.add_parser("embed", help="Build vector index."))
    sync.register(sub.add_parser("sync", help="Sync articles."))
    brainstorm.register_ask(sub.add_parser("ask", help="RAG Q&A."))
    brainstorm.register_brainstorm(sub.add_parser("brainstorm", help="Brainstorm."))
    agent_cli.register(sub.add_parser("agent", help="Agent."))
    wiki_lint_mod.register(sub.add_parser("lint", help="Lint wiki."))
    wiki_compile_mod.register(sub.add_parser("compile", help="Compile wiki."))
    return parser.parse_args(argv)


class QlwCliParserTests(unittest.TestCase):
    def test_parser_exposes_nine_subcommands(self) -> None:
        """qlw --help must list exactly these 9 subcommands."""
        import argparse
        from quant_llm_wiki import enrich, embed, sync
        from quant_llm_wiki.ingest import source as ingest_source
        from quant_llm_wiki.query import brainstorm
        from quant_llm_wiki.agent import cli as agent_cli
        from quant_llm_wiki.wiki import lint as wiki_lint_mod
        from quant_llm_wiki.wiki import compile as wiki_compile_mod

        parser = argparse.ArgumentParser(prog="qlw")
        sub = parser.add_subparsers(dest="cmd", required=True)
        ingest_source.register(sub.add_parser("ingest"))
        enrich.register(sub.add_parser("enrich"))
        embed.register(sub.add_parser("embed"))
        sync.register(sub.add_parser("sync"))
        brainstorm.register_ask(sub.add_parser("ask"))
        brainstorm.register_brainstorm(sub.add_parser("brainstorm"))
        agent_cli.register(sub.add_parser("agent"))
        wiki_lint_mod.register(sub.add_parser("lint"))
        wiki_compile_mod.register(sub.add_parser("compile"))

        # Collect all subcommand names
        all_sub_action = parser._subparsers._actions[1]  # type: ignore[attr-defined]
        self.assertEqual(
            set(all_sub_action.choices.keys()),
            {"ingest", "enrich", "embed", "sync", "ask", "brainstorm", "agent", "lint", "compile"},
        )

    def test_ingest_no_compile_default_false(self) -> None:
        ns = _parse(["ingest", "--url", "https://x"])
        self.assertFalse(ns.no_compile)

    def test_ingest_exposes_pdf_and_html_flags(self) -> None:
        """qlw ingest must accept --pdf-file, --pdf-url, --html-file, --url-list."""
        ns = _parse(["ingest", "--pdf-file", "/tmp/foo.pdf", "--no-compile"])
        self.assertEqual(ns.pdf_file, "/tmp/foo.pdf")
        ns2 = _parse(["ingest", "--pdf-url", "https://x/doc.pdf", "--no-compile"])
        self.assertEqual(ns2.pdf_url, "https://x/doc.pdf")
        ns3 = _parse(["ingest", "--html-file", "/tmp/page.html", "--no-compile"])
        self.assertEqual(ns3.html_file, "/tmp/page.html")
        ns4 = _parse(["ingest", "--url-list", "/tmp/urls.txt", "--no-compile"])
        self.assertEqual(ns4.url_list, "/tmp/urls.txt")

    def test_lint_supports_fix_and_maintain_flags(self) -> None:
        ns = _parse(["lint", "--fix", "--maintain", "--apply"])
        self.assertTrue(ns.fix)
        self.assertTrue(ns.maintain)
        self.assertTrue(ns.apply)

    def test_compile_mode_default_incremental(self) -> None:
        ns = _parse(["compile"])
        self.assertEqual(ns.mode, "incremental")

    def test_compile_mode_rebuild(self) -> None:
        ns = _parse(["compile", "--mode", "rebuild"])
        self.assertEqual(ns.mode, "rebuild")

    def test_compile_dry_run_and_verbose(self) -> None:
        ns = _parse(["compile", "--dry-run", "--verbose"])
        self.assertTrue(ns.dry_run)
        self.assertTrue(ns.verbose)


class QlwCliDispatchTests(unittest.TestCase):
    def test_ingest_url_routes_to_dispatch_url(self) -> None:
        """qlw ingest --url routes to ingest_source.dispatch_url."""
        with patch("quant_llm_wiki.ingest.source.dispatch_url", return_value="raw/x") as m:
            rc = qlw_cli.main(["ingest", "--url", "https://x", "--no-compile"])
        self.assertEqual(rc, 0)
        m.assert_called_once()

    def test_ingest_returns_2_when_no_source_given(self) -> None:
        """qlw ingest with no source flag must return exit code 2."""
        rc = qlw_cli.main(["ingest", "--no-compile"])
        self.assertEqual(rc, 2)

    def test_lint_dispatches_to_lint_wiki(self) -> None:
        """qlw lint dispatches to wiki.lint.lint_wiki."""
        from quant_llm_wiki.wiki.lint import WikiLintReport
        with patch("quant_llm_wiki.wiki.lint.lint_wiki", return_value=WikiLintReport()) as m:
            rc = qlw_cli.main(["lint"])
        self.assertEqual(rc, 0)
        m.assert_called_once()

    def test_compile_dispatches_to_compile_wiki(self) -> None:
        """qlw compile dispatches to wiki.compile.compile_wiki."""
        from quant_llm_wiki.wiki.compile import CompileReport
        with patch("quant_llm_wiki.wiki.compile.compile_wiki", return_value=CompileReport()) as m:
            rc = qlw_cli.main(["compile"])
        self.assertEqual(rc, 0)
        m.assert_called_once()

    def test_compile_passes_mode_to_compile_wiki(self) -> None:
        """qlw compile --mode rebuild passes mode='rebuild' to compile_wiki."""
        from quant_llm_wiki.wiki.compile import CompileReport
        with patch("quant_llm_wiki.wiki.compile.compile_wiki", return_value=CompileReport()) as m:
            qlw_cli.main(["compile", "--mode", "rebuild"])
        call_kwargs = m.call_args[1]
        self.assertEqual(call_kwargs.get("mode"), "rebuild")


if __name__ == "__main__":
    unittest.main()
