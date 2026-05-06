"""Layer 3: Agent routing tests — verify correct tool selection with FakeChatOpenAI."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.robustness.conftest import (
    RobustTestBase,
    ArticleFixtureFactory,
    FakeChatOpenAI,
)


class TestAgentRouting(RobustTestBase):
    """Verify the agent routes to the correct tool based on user input."""

    def _run_agent_with_fake_llm(self, tool_name, tool_args, user_message="test"):
        """Build agent with FakeChatOpenAI, invoke it, return result and fake LLM."""
        from langgraph.prebuilt import create_react_agent
        from quant_llm_wiki.agent.tools import ALL_TOOLS
        from quant_llm_wiki.agent.prompts import SYSTEM_PROMPT

        fake_llm = FakeChatOpenAI(
            tool_sequence=[(tool_name, tool_args)],
            final_response="Done.",
        )

        agent = create_react_agent(
            model=fake_llm,
            tools=ALL_TOOLS,
            prompt=SYSTEM_PROMPT,
        )

        result = agent.invoke({"messages": [{"role": "user", "content": user_message}]})
        return result, fake_llm

    def test_route_list_articles(self):
        result, fake = self._run_agent_with_fake_llm(
            "list_articles", {"source_dir": "raw"},
            "Show me all articles",
        )
        # Agent completed without error
        self.assertTrue(len(fake.calls_made) >= 1)
        messages = result.get("messages", [])
        self.assertTrue(len(messages) > 0)

    def test_route_review_articles(self):
        result, fake = self._run_agent_with_fake_llm(
            "review_articles", {"source_dir": "raw"},
            "Review the raw articles",
        )
        self.assertTrue(len(fake.calls_made) >= 1)

    def test_route_set_article_status(self):
        article_dir = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "route_test_article"
        )
        result, fake = self._run_agent_with_fake_llm(
            "set_article_status",
            {"article_paths": [str(article_dir)], "status": "high_value"},
            "Set this article to high_value",
        )
        self.assertTrue(len(fake.calls_made) >= 1)
        # Verify the tool actually ran
        content = (article_dir / "article.md").read_text(encoding="utf-8")
        self.assertIn("status: high_value", content)

    @patch("quant_llm_wiki.shared.embed_text")
    @patch("quant_llm_wiki.shared.get_llm_config", return_value=("fake-key", "https://fake.url/v4", "glm-4.7"))
    def test_route_embed_knowledge(self, mock_config, mock_embed):
        from tests.robustness.conftest import MockLLMFactory
        mock_embed.side_effect = lambda text, model=None: MockLLMFactory.make_embed_text_mock()(text, model)

        result, fake = self._run_agent_with_fake_llm(
            "embed_knowledge", {"force": False},
            "Update the vector index",
        )
        self.assertTrue(len(fake.calls_made) >= 1)

    def test_route_query_ask(self):
        # query_knowledge_base with no articles will return "No candidate"
        result, fake = self._run_agent_with_fake_llm(
            "query_knowledge_base",
            {"query": "What strategies use momentum?", "mode": "ask"},
            "What strategies use momentum?",
        )
        self.assertTrue(len(fake.calls_made) >= 1)

    def test_route_query_brainstorm(self):
        result, fake = self._run_agent_with_fake_llm(
            "query_knowledge_base",
            {"query": "New ideas for volatility", "mode": "brainstorm"},
            "Brainstorm new ideas about volatility",
        )
        self.assertTrue(len(fake.calls_made) >= 1)

    @patch("quant_llm_wiki.ingest.wechat.fetch_html", side_effect=Exception("Network error"))
    def test_route_ingest_article(self, mock_fetch):
        result, fake = self._run_agent_with_fake_llm(
            "ingest_article",
            {"url": "https://example.com/article"},
            "Ingest this URL: https://example.com/article",
        )
        self.assertTrue(len(fake.calls_made) >= 1)


class TestMultiTurnRouting(RobustTestBase):
    """Verify multi-step tool chains work correctly."""

    def test_review_then_set_status(self):
        from langgraph.prebuilt import create_react_agent
        from quant_llm_wiki.agent.tools import ALL_TOOLS
        from quant_llm_wiki.agent.prompts import SYSTEM_PROMPT

        article_dir = ArticleFixtureFactory.create_raw_article(
            self.tmp_root, "multi_turn_article", title="Multi-Turn Test"
        )

        fake_llm = FakeChatOpenAI(
            tool_sequence=[
                ("review_articles", {"source_dir": "raw"}),
                ("set_article_status", {
                    "article_paths": [str(article_dir)],
                    "status": "reviewed",
                }),
            ],
            final_response="All done. Articles reviewed and status updated.",
        )

        agent = create_react_agent(
            model=fake_llm,
            tools=ALL_TOOLS,
            prompt=SYSTEM_PROMPT,
        )

        result = agent.invoke({
            "messages": [{"role": "user", "content": "Review articles, then set to reviewed"}]
        })

        # 2 tool calls + 1 final response = 3 LLM calls
        self.assertEqual(len(fake_llm.calls_made), 3)

        # Article stays under raw/; status is now reviewed in frontmatter
        self.assertTrue(article_dir.exists())
        self.assertIn("status: reviewed", (article_dir / "article.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
