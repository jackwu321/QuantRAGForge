"""Shared test infrastructure for robustness tests.

Provides:
- RobustTestBase: unittest.TestCase with isolated temp dirs and patched module paths
- ArticleFixtureFactory: creates realistic article directories
- MockLLMFactory: mock factories for LLM/embedding calls
- FakeChatOpenAI: fake LLM for agent routing tests
"""
from __future__ import annotations

import hashlib
import random
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage


# ---------------------------------------------------------------------------
# RobustTestBase — isolated file system + patched module constants
# ---------------------------------------------------------------------------


class RobustTestBase(unittest.TestCase):
    """Base test class that creates an isolated temp directory tree and patches
    all module-level path constants so tools operate in the temp environment."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)

        # Create full directory structure
        for d in (
            "raw",
            "schema",
            "vector_store",
            "sources/processed",
            "outputs/brainstorms",
        ):
            (self.tmp_root / d).mkdir(parents=True, exist_ok=True)

        # Import modules whose constants need patching
        import quant_llm_wiki.shared as kb_shared
        import agent.tools as tools_mod
        import quant_llm_wiki.embed as embed_mod
        import quant_llm_wiki.query.brainstorm as brainstorm_mod

        # Store originals
        self._originals = {
            "kb_shared.ROOT": kb_shared.ROOT,
            "kb_shared.WIKI_DIR": kb_shared.WIKI_DIR,
            "kb_shared.WIKI_STATE_PATH": kb_shared.WIKI_STATE_PATH,
            "tools.KB_ROOT": tools_mod.KB_ROOT,
            "embed.VECTOR_STORE_DIR": embed_mod.VECTOR_STORE_DIR,
            "embed.FAILURE_LIST_PATH": embed_mod.FAILURE_LIST_PATH,
            "brainstorm.VECTOR_STORE_DIR": brainstorm_mod.VECTOR_STORE_DIR,
            "brainstorm.WIKI_DIR": brainstorm_mod.WIKI_DIR,
        }

        # Patch to temp dirs
        kb_shared.ROOT = self.tmp_root
        kb_shared.WIKI_DIR = self.tmp_root / "wiki"
        kb_shared.WIKI_STATE_PATH = self.tmp_root / "wiki" / "state.json"
        tools_mod.KB_ROOT = self.tmp_root
        embed_mod.VECTOR_STORE_DIR = self.tmp_root / "vector_store"
        embed_mod.FAILURE_LIST_PATH = (
            self.tmp_root / "sources" / "processed" / "embed_failures.txt"
        )
        brainstorm_mod.VECTOR_STORE_DIR = self.tmp_root / "vector_store"
        brainstorm_mod.WIKI_DIR = self.tmp_root / "wiki"

    def tearDown(self):
        import quant_llm_wiki.shared as kb_shared
        import agent.tools as tools_mod
        import quant_llm_wiki.embed as embed_mod
        import quant_llm_wiki.query.brainstorm as brainstorm_mod

        kb_shared.ROOT = self._originals["kb_shared.ROOT"]
        kb_shared.WIKI_DIR = self._originals["kb_shared.WIKI_DIR"]
        kb_shared.WIKI_STATE_PATH = self._originals["kb_shared.WIKI_STATE_PATH"]
        tools_mod.KB_ROOT = self._originals["tools.KB_ROOT"]
        embed_mod.VECTOR_STORE_DIR = self._originals["embed.VECTOR_STORE_DIR"]
        embed_mod.FAILURE_LIST_PATH = self._originals["embed.FAILURE_LIST_PATH"]
        brainstorm_mod.VECTOR_STORE_DIR = self._originals["brainstorm.VECTOR_STORE_DIR"]
        brainstorm_mod.WIKI_DIR = self._originals["brainstorm.WIKI_DIR"]

        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# ArticleFixtureFactory
# ---------------------------------------------------------------------------


class ArticleFixtureFactory:
    """Creates realistic article directories with proper frontmatter."""

    @staticmethod
    def create_article(
        base_dir: Path,
        article_id: str,
        title: str = "Test Article",
        status: str = "raw",
        content_type: str = "methodology",
        brainstorm_value: str = "high",
        summary: str = "A test summary for this article.",
        body_content: str = "Some main content paragraph.",
        idea_blocks: list[str] | None = None,
        combination_hooks: list[str] | None = None,
        transfer_targets: list[str] | None = None,
        failure_modes: list[str] | None = None,
        llm_enriched: bool = True,
    ) -> Path:
        """Create an article directory with article.md. Returns the directory path."""
        article_dir = base_dir / article_id
        article_dir.mkdir(parents=True, exist_ok=True)

        fm_lines = [
            f"title: {title}",
            f"status: {status}",
            f"content_type: {content_type}",
            f"brainstorm_value: {brainstorm_value}",
            f"summary: {summary}",
        ]
        if idea_blocks:
            fm_lines.append(f"idea_blocks: {idea_blocks}")
        if combination_hooks:
            fm_lines.append(f"combination_hooks: {combination_hooks}")
        if transfer_targets:
            fm_lines.append(f"transfer_targets: {transfer_targets}")
        if failure_modes:
            fm_lines.append(f"failure_modes: {failure_modes}")

        frontmatter = "\n".join(fm_lines)
        md = f"---\n{frontmatter}\n---\n\n## Main Content\n\n{body_content}\n"
        (article_dir / "article.md").write_text(md, encoding="utf-8")
        if llm_enriched:
            import json
            source = {"llm_enriched": True}
            (article_dir / "source.json").write_text(json.dumps(source), encoding="utf-8")
        return article_dir

    @classmethod
    def create_raw_article(cls, tmp_root: Path, article_id: str, **kwargs) -> Path:
        base = tmp_root / "raw"
        kwargs.setdefault("status", "raw")
        return cls.create_article(base, article_id, **kwargs)

    @classmethod
    def create_reviewed_article(cls, tmp_root: Path, article_id: str, **kwargs) -> Path:
        base = tmp_root / "raw"
        kwargs.setdefault("status", "reviewed")
        return cls.create_article(base, article_id, **kwargs)

    @classmethod
    def create_high_value_article(cls, tmp_root: Path, article_id: str, **kwargs) -> Path:
        base = tmp_root / "raw"
        kwargs.setdefault("status", "high_value")
        return cls.create_article(base, article_id, **kwargs)

    @staticmethod
    def create_malformed_article(base_dir: Path, article_id: str, content: str) -> Path:
        """Create an article with arbitrary content (for edge case testing)."""
        article_dir = base_dir / article_id
        article_dir.mkdir(parents=True, exist_ok=True)
        (article_dir / "article.md").write_text(content, encoding="utf-8")
        return article_dir


# ---------------------------------------------------------------------------
# MockLLMFactory
# ---------------------------------------------------------------------------


def _deterministic_embedding(text: str, dim: int = 10) -> list[float]:
    """Generate a deterministic, normalized embedding from text hash."""
    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


class MockLLMFactory:
    """Factory for creating mocks of LLM API functions."""

    @staticmethod
    def make_embed_text_mock(dim: int = 10) -> MagicMock:
        """Returns a mock for embed_text that produces deterministic embeddings."""
        mock = MagicMock()
        mock.side_effect = lambda text, model=None: _deterministic_embedding(text, dim)
        return mock

    @staticmethod
    def make_call_llm_chat_mock(response: str = "Mock LLM response") -> MagicMock:
        """Returns a mock for call_llm_chat / call_zhipu_chat."""
        mock = MagicMock(return_value=response)
        return mock

    @staticmethod
    def make_post_llm_json_mock(enrich_response: dict | None = None) -> MagicMock:
        """Returns a mock for post_llm_json that returns enrichment JSON."""
        if enrich_response is None:
            enrich_response = MockLLMFactory.make_enrich_response()
        mock = MagicMock(return_value=enrich_response)
        return mock

    @staticmethod
    def make_enrich_response() -> dict:
        """Returns a realistic enrichment response matching the schema."""
        return {
            "choices": [
                {
                    "message": {
                        "content": textwrap.dedent("""\
                            {
                                "summary": "Test enriched summary",
                                "research_question": "How does this work?",
                                "core_hypothesis": "It works because X",
                                "signal_framework": "Signal based on Y",
                                "idea_blocks": ["Idea 1: use momentum", "Idea 2: combine with value"],
                                "combination_hooks": ["Hook 1: pair with volatility filter"],
                                "transfer_targets": ["Target 1: apply to crypto markets"],
                                "failure_modes": ["Failure 1: breaks in low liquidity"]
                            }
                        """)
                    }
                }
            ]
        }


# ---------------------------------------------------------------------------
# FakeChatOpenAI — for agent routing tests
# ---------------------------------------------------------------------------


class FakeChatOpenAI(BaseChatModel):
    """Fake LLM that returns predetermined tool calls for agent routing tests.

    Subclasses BaseChatModel so it's compatible with LangGraph's create_react_agent.

    Usage:
        fake = FakeChatOpenAI(
            tool_sequence=[("list_articles", {"source_dir": "raw"})],
            final_response="Done listing articles.",
        )
    """

    tool_sequence: list = []
    final_response: str = "Task completed."
    calls_made: list = []
    _call_index: int = 0

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "fake-test"

    def bind_tools(self, tools, **kwargs):
        """Required by create_react_agent. Returns self since tool calls are predetermined."""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatResult, ChatGeneration

        self.calls_made.append({"messages": messages})

        if self._call_index < len(self.tool_sequence):
            tool_name, tool_args = self.tool_sequence[self._call_index]
            self._call_index += 1
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "id": f"call_{self._call_index:03d}",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            msg = AIMessage(content=self.final_response)

        return ChatResult(generations=[ChatGeneration(message=msg)])
