from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestAgentGraph(unittest.TestCase):
    """Test agent graph creation and basic behavior."""

    @patch("quant_llm_wiki.agent.graph.get_llm_config")
    @patch("quant_llm_wiki.agent.graph.ChatOpenAI")
    def test_create_agent_returns_compiled_graph(self, mock_llm_cls, mock_config):
        mock_config.return_value = ("fake-key", "https://fake.url/v4", "glm-4.7")
        mock_llm_cls.return_value = MagicMock()

        from quant_llm_wiki.agent.graph import create_agent

        agent = create_agent()
        # The compiled graph should have an invoke method
        self.assertTrue(hasattr(agent, "invoke"))

    @patch("quant_llm_wiki.agent.graph.get_llm_config")
    @patch("quant_llm_wiki.agent.graph.ChatOpenAI")
    def test_create_agent_uses_correct_model(self, mock_llm_cls, mock_config):
        mock_config.return_value = ("test-key", "https://test.url/v4", "glm-4.7")
        mock_llm_cls.return_value = MagicMock()

        from quant_llm_wiki.agent.graph import create_agent

        create_agent()
        mock_llm_cls.assert_called_once_with(
            model="glm-4.7",
            api_key="test-key",
            base_url="https://test.url/v4",
            temperature=0.1,
            extra_body=None,
        )

    @patch("quant_llm_wiki.agent.graph.get_llm_config")
    @patch("quant_llm_wiki.agent.graph.ChatOpenAI")
    def test_create_agent_disables_thinking_for_zhipu(self, mock_llm_cls, mock_config):
        # GLM-4.x thinking mode can return the final answer only in
        # reasoning_content with empty content; thinking is disabled on Zhipu.
        mock_config.return_value = (
            "test-key",
            "https://open.bigmodel.cn/api/paas/v4",
            "glm-4.7",
        )
        mock_llm_cls.return_value = MagicMock()

        from quant_llm_wiki.agent.graph import create_agent

        create_agent()
        kwargs = mock_llm_cls.call_args.kwargs
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    @patch("quant_llm_wiki.agent.graph.get_llm_config")
    @patch("quant_llm_wiki.agent.graph.ChatOpenAI")
    def test_create_agent_publishes_runtime_tool_names(self, mock_llm_cls, mock_config):
        # Skills referencing conditionally-registered memory tools are
        # annotated via the runtime tool set; create_agent must publish it.
        mock_config.return_value = ("fake-key", "https://fake.url/v4", "glm-4.7")
        mock_llm_cls.return_value = MagicMock()

        import quant_llm_wiki.agent.skill_registry as skill_registry
        from quant_llm_wiki.agent.graph import create_agent
        from quant_llm_wiki.agent.memory.tools import MEMORY_TOOLS
        from quant_llm_wiki.agent.tools import ALL_TOOLS

        try:
            create_agent()
            self.assertEqual(
                skill_registry._RUNTIME_TOOL_NAMES,
                {t.name for t in ALL_TOOLS},
            )
            create_agent(memory_tools=MEMORY_TOOLS)
            self.assertEqual(
                skill_registry._RUNTIME_TOOL_NAMES,
                {t.name for t in ALL_TOOLS} | {t.name for t in MEMORY_TOOLS},
            )
        finally:
            skill_registry.set_runtime_tool_names(None)

    def test_all_tools_registered(self):
        from quant_llm_wiki.agent.tools import ALL_TOOLS

        tool_names = {t.name for t in ALL_TOOLS}
        expected = {
            "ingest_article",
            "enrich_articles",
            "list_articles",
            "review_articles",
            "set_article_status",
            "embed_knowledge",
            "query_knowledge_base",
            "deep_brainstorm",
            "compile_wiki",
            "audit_wiki",
            "list_concepts",
            "set_concept_status",
            "read_wiki",
            "list_skills",
            "read_skill",
            "save_strategy_brief",
        }
        self.assertEqual(tool_names, expected)

    def test_all_tools_have_descriptions(self):
        from quant_llm_wiki.agent.tools import ALL_TOOLS

        for tool in ALL_TOOLS:
            self.assertTrue(
                len(tool.description) > 10,
                f"Tool {tool.name} has insufficient description",
            )


if __name__ == "__main__":
    unittest.main()
