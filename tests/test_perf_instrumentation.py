import io
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr
from pathlib import Path

from quant_llm_wiki.query import brainstorm as brainstorm_mod

# Make scripts/ importable for _parse_event tests.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))


PERF_LINE_RE = re.compile(r"^\[qlw-perf\] ([a-z_]+): (.+)$")


def parse_perf_lines(stderr: str) -> list[dict]:
    """Return a list of {event, fields} dicts, one per [qlw-perf] line."""
    out = []
    for line in stderr.splitlines():
        m = PERF_LINE_RE.match(line)
        if not m:
            continue
        event = m.group(1)
        fields = {}
        for kv in m.group(2).split():
            if "=" in kv:
                k, v = kv.split("=", 1)
                fields[k] = v
        out.append({"event": event, "fields": fields})
    return out


class RetrieveConceptArticlesTimingTests(unittest.TestCase):
    def test_emits_timing_line_with_mode_and_ms(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}):
                with redirect_stderr(buf):
                    brainstorm_mod._retrieve_concept_articles(
                        "anything", top_k=3, wiki_dir=wiki_dir,
                    )
            events = parse_perf_lines(buf.getvalue())
            timing = [e for e in events if e["event"] == "_retrieve_concept_articles"]
            self.assertEqual(len(timing), 1, f"expected exactly 1 timing line, got {buf.getvalue()!r}")
            f = timing[0]["fields"]
            self.assertIn("ms", f)
            self.assertIn("mode", f)
            self.assertIn("results", f)
            self.assertIn(f["mode"], {"chroma", "lexical", "empty"})
            ms_value = float(f["ms"])
            self.assertGreaterEqual(ms_value, 0.0)
            self.assertLess(ms_value, 5000.0,
                            "ms should be milliseconds — a value this large suggests wrong unit or extreme slowness")
            self.assertEqual(f["results"], "0")  # empty wiki → no concepts

    def test_lexical_fallback_emits_lexical_mode(self):
        """When the concepts dir is populated but Chroma yields nothing,
        the function should fall through to lexical and tag the line accordingly."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            concepts_dir = wiki_dir / "concepts"
            concepts_dir.mkdir(parents=True)
            # One concept file — enough to make the lexical fallback actually
            # have something to score, even if "anything" doesn't match.
            (concepts_dir / "alpha.md").write_text(
                "---\ntitle: Alpha\nslug: alpha\naliases: []\n"
                "retrieval_hints: [unrelated_topic]\n---\nbody\n",
                encoding="utf-8",
            )
            # Empty vector_store_dir → Chroma path returns nothing, lexical takes over
            store_dir = Path(tmp) / "vector_store"
            store_dir.mkdir()
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}):
                with redirect_stderr(buf):
                    brainstorm_mod._retrieve_concept_articles(
                        "anything", top_k=3,
                        vector_store_dir=store_dir, wiki_dir=wiki_dir,
                    )
            events = parse_perf_lines(buf.getvalue())
            timing = [e for e in events if e["event"] == "_retrieve_concept_articles"]
            self.assertEqual(len(timing), 1, f"got {buf.getvalue()!r}")
            self.assertEqual(timing[0]["fields"]["mode"], "lexical")
            ms_value = float(timing[0]["fields"]["ms"])
            self.assertGreaterEqual(ms_value, 0.0)
            self.assertLess(ms_value, 5000.0,
                            "ms should be milliseconds — a value this large suggests wrong unit or extreme slowness")


class RetrieveBlocksTimingTests(unittest.TestCase):
    def test_retrieve_blocks_emits_total_ms(self):
        from quant_llm_wiki.query.brainstorm import retrieve_blocks
        from quant_llm_wiki.shared import KnowledgeNote

        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            (kb_root / "wiki" / "concepts").mkdir(parents=True)
            (kb_root / "wiki" / "INDEX.md").write_text("# index\n", encoding="utf-8")
            # Note with absolute article_dir → triggers wiki branch
            note = KnowledgeNote(
                article_dir=kb_root / "articles" / "x" / "article.md",
                source_dir="articles",
                frontmatter={"title": "x", "content_type": ""},
                body="hello world",
            )
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}), \
                 unittest.mock.patch(
                     "quant_llm_wiki.query.brainstorm._wiki_is_healthy_for_query",
                     return_value=True,
                 ):
                with redirect_stderr(buf):
                    retrieve_blocks(
                        [note], "any query", top_k=3,
                        command="brainstorm", retrieval_mode="keyword",
                        kb_root=kb_root,
                    )
            events = parse_perf_lines(buf.getvalue())
            rb = [e for e in events if e["event"] == "retrieve_blocks"]
            self.assertEqual(len(rb), 1)
            f = rb[0]["fields"]
            # Log emits real measurements only. The "concept_retrievals == 1"
            # invariant is locked by tests/test_brainstorm_with_wiki.py's
            # spy test, not by a hardcoded log field — printing a constant
            # would silently lie if a future refactor adds fallback retrieval.
            self.assertNotIn("concept_retrievals", f)
            self.assertIn("wiki_blocks", f)
            self.assertIn("excluded_articles", f)
            self.assertIn("total_ms", f)
            ms_value = float(f["total_ms"])
            self.assertGreaterEqual(ms_value, 0.0)
            self.assertLess(ms_value, 5000.0)


class CompileWikiTimingTests(unittest.TestCase):
    def test_compile_emits_phase_timings(self):
        from quant_llm_wiki.wiki import compile as compile_mod
        # ConceptAssignment (not AssignmentResult) is in quant_llm_wiki.wiki.compile_llm
        from quant_llm_wiki.wiki.compile_llm import ConceptAssignment, RecompileResult

        with tempfile.TemporaryDirectory() as tmp:
            kb_root = Path(tmp)
            (kb_root / "wiki").mkdir()
            article_dir = kb_root / "articles" / "a1"
            article_dir.mkdir(parents=True)
            (article_dir / "article.md").write_text(
                "---\ntitle: A1\ncontent_type: paper\n---\nhello\n",
                encoding="utf-8",
            )

            fake_assign = ConceptAssignment(
                existing_concepts=[],
                proposed_new_concepts=[],
                error="",
            )
            fake_recompile = RecompileResult(
                synthesis="s", definition="d", related_concepts=[],
                key_idea_blocks=[], variants=[], common_combinations=[],
                transfer_targets=[], failure_modes=[], open_questions=[],
                error="",
            )

            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}), \
                 unittest.mock.patch.object(compile_mod, "assign_concepts", return_value=fake_assign), \
                 unittest.mock.patch.object(compile_mod, "recompile_concept", return_value=fake_recompile):
                with redirect_stderr(buf):
                    compile_mod.compile_wiki(
                        kb_root=kb_root,
                        source_dirs=["articles"],
                        mode="incremental",
                        dry_run=True,
                    )
            events = parse_perf_lines(buf.getvalue())
            cw = [e for e in events if e["event"] == "compile_wiki"]
            self.assertEqual(len(cw), 1, f"got {buf.getvalue()!r}")
            f = cw[0]["fields"]
            for key in ("articles", "affected_concepts", "reverse_index_size", "assign_ms", "recompile_ms"):
                self.assertIn(key, f, f"missing {key} in {f}")
            assign_ms = float(f["assign_ms"])
            recompile_ms = float(f["recompile_ms"])
            self.assertGreaterEqual(assign_ms, 0.0)
            self.assertGreaterEqual(recompile_ms, 0.0)
            self.assertLess(assign_ms, 10000.0)
            self.assertLess(recompile_ms, 10000.0)


class RetrieveConceptArticlesChromaTests(unittest.TestCase):
    def test_chroma_mode_emits_chroma(self):
        """When _retrieve_concepts_via_chroma returns results, mode should be 'chroma'."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            (wiki_dir / "concepts").mkdir(parents=True)
            fake_concepts = [{"slug": "s", "title": "T", "body_text": "b", "sources": []}]
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}), \
                 unittest.mock.patch.object(brainstorm_mod, "_retrieve_concepts_via_chroma",
                                            return_value=fake_concepts):
                with redirect_stderr(buf):
                    brainstorm_mod._retrieve_concept_articles(
                        "anything", top_k=3, wiki_dir=wiki_dir,
                    )
            events = parse_perf_lines(buf.getvalue())
            timing = [e for e in events if e["event"] == "_retrieve_concept_articles"]
            self.assertEqual(len(timing), 1, f"got {buf.getvalue()!r}")
            self.assertEqual(timing[0]["fields"]["mode"], "chroma")
            self.assertEqual(timing[0]["fields"]["results"], "1")

    def test_empty_mode_when_no_concepts_dir(self):
        """When the concepts directory does not exist, mode should be 'empty'."""
        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_dir.mkdir()
            # No concepts subdir created — _retrieve_concept_articles should early-exit.
            buf = io.StringIO()
            with unittest.mock.patch.dict(os.environ, {"QLW_PERF_DEBUG": "1"}):
                with redirect_stderr(buf):
                    brainstorm_mod._retrieve_concept_articles(
                        "anything", top_k=3, wiki_dir=wiki_dir,
                    )
            events = parse_perf_lines(buf.getvalue())
            timing = [e for e in events if e["event"] == "_retrieve_concept_articles"]
            self.assertEqual(len(timing), 1, f"got {buf.getvalue()!r}")
            self.assertEqual(timing[0]["fields"]["mode"], "empty")
            self.assertEqual(timing[0]["fields"]["results"], "0")


class ParseEventTests(unittest.TestCase):
    def setUp(self):
        from benchmark_perf import _parse_event
        self._parse_event = _parse_event

    def test_multiple_calls_sets_calls_count(self):
        """When the same event appears twice in stderr, calls should reflect both."""
        stderr = (
            "[qlw-perf] myevent: ms=1.2 mode=lexical\n"
            "[qlw-perf] myevent: ms=3.4 mode=chroma\n"
        )
        result = self._parse_event(stderr, "myevent")
        self.assertEqual(result["calls"], 2)
        # Last value wins for numeric fields (dict overwritten by second line)
        self.assertAlmostEqual(result["ms"], 3.4, places=5)

    def test_value_error_falls_back_to_str(self):
        """Non-numeric values should be stored as strings rather than raising."""
        stderr = "[qlw-perf] myevent: mode=lexical flag=yes\n"
        result = self._parse_event(stderr, "myevent")
        self.assertEqual(result["mode"], "lexical")
        self.assertEqual(result["flag"], "yes")
        self.assertEqual(result["calls"], 1)


class EmitPerfTests(unittest.TestCase):
    def test_zero_cost_when_env_not_set(self):
        """_emit_perf should write nothing to stderr when QLW_PERF_DEBUG is unset."""
        from quant_llm_wiki.shared_perf import _emit_perf
        buf = io.StringIO()
        env_without_debug = {k: v for k, v in os.environ.items() if k != "QLW_PERF_DEBUG"}
        with unittest.mock.patch.dict(os.environ, env_without_debug, clear=True), \
             redirect_stderr(buf):
            for _ in range(10_000):
                _emit_perf("noop", ms=0.0, mode="test")
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
