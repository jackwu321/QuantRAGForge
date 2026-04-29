from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestAgentGraph(unittest.TestCase):
    """Test agent graph creation and basic behavior."""

    @patch("agent.graph.get_llm_config")
    @patch("agent.graph.ChatOpenAI")
    def test_create_agent_returns_compiled_graph(self, mock_llm_cls, mock_config):
        mock_config.return_value = ("fake-key", "https://fake.url/v4", "glm-4.7")
        mock_llm_cls.return_value = MagicMock()

        from agent.graph import create_agent

        agent = create_agent()
        # The compiled graph should have an invoke method
        self.assertTrue(hasattr(agent, "invoke"))

    @patch("agent.graph.get_llm_config")
    @patch("agent.graph.ChatOpenAI")
    def test_create_agent_uses_correct_model(self, mock_llm_cls, mock_config):
        mock_config.return_value = ("test-key", "https://test.url/v4", "glm-4.7")
        mock_llm_cls.return_value = MagicMock()

        from agent.graph import create_agent

        create_agent()
        mock_llm_cls.assert_called_once_with(
            model="glm-4.7",
            api_key="test-key",
            base_url="https://test.url/v4",
            temperature=0.1,
        )

    def test_all_tools_registered(self):
        from agent.tools import ALL_TOOLS

        tool_names = {t.name for t in ALL_TOOLS}
        expected = {
            "ingest_article",
            "enrich_articles",
            "list_articles",
            "review_articles",
            "set_article_status",
            "sync_articles",
            "embed_knowledge",
            "query_knowledge_base",
            "compile_wiki",
            "list_concepts",
            "set_concept_status",
            "read_wiki",
        }
        self.assertEqual(tool_names, expected)

    def test_all_tools_have_descriptions(self):
        from agent.tools import ALL_TOOLS

        for tool in ALL_TOOLS:
            self.assertTrue(
                len(tool.description) > 10,
                f"Tool {tool.name} has insufficient description",
            )


if __name__ == "__main__":
    unittest.main()
