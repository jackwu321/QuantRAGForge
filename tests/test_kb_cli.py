"""Tests for kb.py — the unified ingest/query/lint/compile/embed CLI."""
import unittest
from unittest.mock import patch

import kb


class KbCliParserTests(unittest.TestCase):
    def test_parser_exposes_five_subcommands(self) -> None:
        parser = kb.build_parser()
        sub = parser._subparsers._actions[1]  # type: ignore[attr-defined]
        self.assertEqual(set(sub.choices.keys()), {"ingest", "query", "lint", "compile", "embed"})

    def test_query_requires_query_flag(self) -> None:
        with self.assertRaises(SystemExit):
            kb.build_parser().parse_args(["query"])

    def test_query_default_mode_is_ask(self) -> None:
        ns = kb.build_parser().parse_args(["query", "--query", "x"])
        self.assertEqual(ns.mode, "ask")
        self.assertFalse(ns.no_file_back)

    def test_lint_supports_fix_and_maintain_flags(self) -> None:
        ns = kb.build_parser().parse_args(["lint", "--fix", "--maintain", "--apply"])
        self.assertTrue(ns.fix)
        self.assertTrue(ns.maintain)
        self.assertTrue(ns.apply)

    def test_ingest_no_compile_default_false(self) -> None:
        ns = kb.build_parser().parse_args(["ingest", "--url", "https://x"])
        self.assertFalse(ns.no_compile)


class KbCliDispatchTests(unittest.TestCase):
    def test_ingest_dispatch_routes_to_dispatch_url(self) -> None:
        with patch("ingest_source.dispatch_url", return_value="raw/x") as m:
            rc = kb.cmd_ingest(kb.build_parser().parse_args(
                ["ingest", "--url", "https://x", "--no-compile"]
            ))
        self.assertEqual(rc, 0)
        m.assert_called_once()

    def test_query_dispatch_invokes_brainstorm_main(self) -> None:
        with patch("quant_llm_wiki.query.brainstorm.main", return_value=0) as m:
            rc = kb.cmd_query(kb.build_parser().parse_args(
                ["query", "--query", "test", "--no-file-back"]
            ))
        self.assertEqual(rc, 0)
        m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
