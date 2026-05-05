"""Tests for wiki_maintain — Steps 6 (maintenance) and 7 (query feedback)."""
import tempfile
import unittest
from pathlib import Path

import wiki_maintain
from wiki_seed import bootstrap_wiki
from wiki_state import load_wiki_state


class QueryFeedbackTests(unittest.TestCase):
    def _setup_kb(self, root: Path) -> Path:
        bootstrap_wiki(root / "wiki")
        out_dir = root / "outputs" / "brainstorms"
        out_dir.mkdir(parents=True)
        return out_dir

    def _write_output(self, out_dir: Path, name: str, retrieved: list[str]) -> Path:
        p = out_dir / name
        body = (
            "# Brainstorm Result\n\n"
            "Query: q\n\n"
            "## Retrieved Sources\n\n"
            + "\n".join(f"- {s}" for s in retrieved)
            + "\n\n## Output\n\nbody\n"
        )
        p.write_text(body, encoding="utf-8")
        return p

    def test_writes_log_to_wiki_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = self._setup_kb(root)
            concept_path = root / "wiki" / "concepts" / "momentum-strategies.md"
            out = self._write_output(out_dir, "2026-05-05_q_brainstorm.md", [str(concept_path)])
            log_path = wiki_maintain.append_query_log(
                root, query="some query", mode="brainstorm", output_path=out
            )
            self.assertIsNotNone(log_path)
            assert log_path is not None  # for type narrowing
            self.assertTrue(log_path.exists())
            text = log_path.read_text(encoding="utf-8")
            self.assertIn('cited_concepts: ["momentum-strategies"]', text)
            self.assertIn("mode: brainstorm", text)

    def test_bumps_state_importance_on_cited_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = self._setup_kb(root)
            concept_path = root / "wiki" / "concepts" / "etf-rotation.md"
            out = self._write_output(out_dir, "2026-05-05_x_ask.md", [str(concept_path)])
            wiki_maintain.append_query_log(root, query="rotation?", mode="ask", output_path=out)
            state = load_wiki_state(root / "wiki" / "state.json")
            entry = state.concepts["etf-rotation"]
            self.assertGreater(entry.importance, 0.0)
            self.assertTrue(any("rotation" in h for h in entry.retrieval_hints))

    def test_returns_none_when_no_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_kb(root)
            log = wiki_maintain.append_query_log(root, query="ghost", mode="ask")
            self.assertIsNone(log)


class MaintenanceRunTests(unittest.TestCase):
    def test_run_maintenance_idempotent_on_clean_wiki(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_wiki(root / "wiki")
            r1 = wiki_maintain.run_maintenance(root, apply=False, write_report=False)
            r2 = wiki_maintain.run_maintenance(root, apply=False, write_report=False)
            self.assertEqual(r1.summary(), r2.summary())

    def test_writes_maintenance_report_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_wiki(root / "wiki")
            wiki_maintain.run_maintenance(root, apply=False, write_report=True)
            report_path = root / "wiki" / "maintenance_report.md"
            self.assertTrue(report_path.exists())
            text = report_path.read_text(encoding="utf-8")
            self.assertIn("Wiki Maintenance Report", text)

    def test_unmapped_source_cluster_surfaces_as_new_concept_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_wiki(root / "wiki")
            sources_dir = root / "wiki" / "sources"
            sources_dir.mkdir(exist_ok=True)
            for name in ("a.md", "b.md"):
                (sources_dir / name).write_text(
                    "---\n"
                    f"source_path: raw/{name[:1]}/article.md\n"
                    f"title: Source {name[:1].upper()}\n"
                    "content_type: market_review\n"
                    "brainstorm_value: medium\n"
                    "feeds_concepts: []\n"
                    "ingested: 2026-05-04\n"
                    "last_compiled: 2026-05-04\n"
                    "---\n\n"
                    "**One-line takeaway:** t\n\n"
                    "**Idea Blocks (top 3):**\n\n- x\n\n"
                    "**Why it's in the KB:** y\n\n"
                    "**Feeds concepts:** _none_\n",
                    encoding="utf-8",
                )
            r = wiki_maintain.run_maintenance(root, apply=False, write_report=False)
            self.assertEqual(len(r.new_concept_suggestions), 1)
            self.assertIn("market_review", r.new_concept_suggestions[0]["rationale"])


if __name__ == "__main__":
    unittest.main()
