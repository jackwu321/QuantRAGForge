import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import wiki_state
import wiki_schemas


class LoadSaveTests(unittest.TestCase):
    def test_missing_file_returns_empty_v1_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = wiki_state.load_wiki_state(path)
            self.assertEqual(state.schema_version, wiki_state.SCHEMA_VERSION)
            self.assertEqual(state.sources, {})
            self.assertEqual(state.concepts, {})

    def test_invalid_json_returns_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("not json", encoding="utf-8")
            state = wiki_state.load_wiki_state(path)
            self.assertEqual(state.sources, {})
            self.assertEqual(state.concepts, {})

    def test_old_schema_returns_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"schema_version":"old","sources":{}}', encoding="utf-8")
            state = wiki_state.load_wiki_state(path)
            self.assertEqual(state.sources, {})

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = wiki_state.WikiState()
            state.sources["articles/x/article.md"] = wiki_state.SourceEntry(
                content_hash="abc123", last_seen="2026-04-30",
                feeds_concepts=["momentum-strategies"],
            )
            state.concepts["momentum-strategies"] = wiki_state.ConceptEntry(
                status="stable", confidence=0.8, importance=0.7, freshness=0.9,
                last_compiled="2026-04-30", compile_version=2, source_count=4,
                conflicts=[], retrieval_hints=["momentum", "动量"],
            )
            wiki_state.save_wiki_state(state, path)
            reloaded = wiki_state.load_wiki_state(path)
            self.assertEqual(reloaded.sources["articles/x/article.md"].content_hash, "abc123")
            self.assertAlmostEqual(reloaded.concepts["momentum-strategies"].confidence, 0.8)
            self.assertEqual(reloaded.concepts["momentum-strategies"].retrieval_hints, ["momentum", "动量"])


class ContentHashTests(unittest.TestCase):
    def test_hash_changes_when_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article = Path(tmp) / "article.md"
            article.write_text("v1", encoding="utf-8")
            h1 = wiki_state.source_content_hash(article)
            article.write_text("v2", encoding="utf-8")
            h2 = wiki_state.source_content_hash(article)
            self.assertNotEqual(h1, h2)

    def test_is_source_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            article = Path(tmp) / "article.md"
            article.write_text("hello", encoding="utf-8")
            state = wiki_state.WikiState()
            self.assertTrue(wiki_state.is_source_changed(state, article))
            wiki_state.update_source_entry(state, article, feeds_concepts=["x"])
            self.assertFalse(wiki_state.is_source_changed(state, article))
            article.write_text("hello world", encoding="utf-8")
            self.assertTrue(wiki_state.is_source_changed(state, article))


class MemoryScoreTests(unittest.TestCase):
    def test_high_confidence_fresh_outranks_low_stale(self) -> None:
        good = wiki_state.concept_memory_score(
            confidence=0.9, importance=0.7, freshness=0.95, source_count=8,
        )
        bad = wiki_state.concept_memory_score(
            confidence=0.2, importance=0.3, freshness=0.1, source_count=1,
        )
        self.assertGreater(good, bad)

    def test_conflicts_reduce_score(self) -> None:
        clean = wiki_state.concept_memory_score(0.7, 0.7, 0.7, 5, conflict_count=0)
        conflicted = wiki_state.concept_memory_score(0.7, 0.7, 0.7, 5, conflict_count=3)
        self.assertGreater(clean, conflicted)

    def test_score_is_non_negative(self) -> None:
        s = wiki_state.concept_memory_score(0.0, 0.0, 0.0, 0, conflict_count=10)
        self.assertGreaterEqual(s, 0.0)

    def test_freshness_decays_with_age(self) -> None:
        old = (date.today() - timedelta(days=120)).isoformat()
        new = date.today().isoformat()
        old_f = wiki_state._freshness_from_date(old)
        new_f = wiki_state._freshness_from_date(new)
        self.assertGreater(new_f, old_f)


class UpdateConceptEntryTests(unittest.TestCase):
    def _make_concept(self, **overrides):
        defaults = dict(
            title="Momentum Strategies",
            slug="momentum-strategies",
            aliases=["momentum", "动量策略"],
            status="stable",
            related_concepts=[],
            sources=["articles/reviewed/a/article.md", "articles/reviewed/b/article.md"],
            content_types=["strategy"],
            last_compiled=date.today().isoformat(),
            compile_version=1,
            synthesis="S",
            definition="D",
            key_idea_blocks=[
                "12-month minus 1-month return [a]",
                "Risk-adjusted variant [b]",
            ],
            variants=[],
            common_combinations=[],
            transfer_targets=[],
            failure_modes=[],
            open_questions=[],
            source_basenames=["a", "b"],
        )
        defaults.update(overrides)
        return wiki_schemas.ConceptArticle(**defaults)

    def test_well_anchored_concept_gets_high_confidence(self) -> None:
        state = wiki_state.WikiState()
        c = self._make_concept()
        wiki_state.update_concept_entry(state, c)
        entry = state.concepts["momentum-strategies"]
        self.assertEqual(entry.confidence, 1.0)
        self.assertGreater(entry.freshness, 0.9)
        self.assertEqual(entry.source_count, 2)
        self.assertIn("momentum", entry.retrieval_hints)

    def test_unanchored_bullet_lowers_confidence(self) -> None:
        state = wiki_state.WikiState()
        c = self._make_concept(key_idea_blocks=[
            "12-month minus 1-month return [a]",
            "Unanchored hand-wave",
        ])
        wiki_state.update_concept_entry(state, c)
        self.assertEqual(state.concepts["momentum-strategies"].confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
