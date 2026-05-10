"""Tests for agent-path surrogate sanitization.

Covers:
- `quant_llm_wiki.agent.graph._sanitize_agent_message` (post_model_hook)
- `quant_llm_wiki.agent.cli._safe_text` (output-boundary helper)
"""
from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages

from quant_llm_wiki.agent.cli import _safe_text
from quant_llm_wiki.agent.graph import _sanitize_agent_message

_REPL = "�"


class SafeTextTests(unittest.TestCase):
    def test_passthrough_clean_str(self):
        self.assertEqual(_safe_text("hello"), "hello")

    def test_replaces_surrogates(self):
        self.assertEqual(_safe_text("a\ud83db"), "a" + _REPL + "b")

    def test_coerces_non_str(self):
        self.assertEqual(_safe_text(42), "42")
        self.assertEqual(_safe_text(None), "None")

    def test_coerced_value_is_utf8_encodable(self):
        # Even when coercing an exception with surrogate-bearing args.
        exc = ValueError("boom\ud83d")
        _safe_text(exc).encode("utf-8")  # must not raise


class SanitizeAgentMessageHookTests(unittest.TestCase):
    def test_no_messages_returns_empty(self):
        self.assertEqual(_sanitize_agent_message({"messages": []}), {})
        self.assertEqual(_sanitize_agent_message({}), {})

    def test_last_not_ai_returns_empty(self):
        state = {"messages": [HumanMessage(content="hi")]}
        self.assertEqual(_sanitize_agent_message(state), {})

    def test_clean_ai_message_is_noop(self):
        state = {"messages": [AIMessage(content="all good")]}
        self.assertEqual(_sanitize_agent_message(state), {})

    def test_sanitizes_str_content(self):
        msg = AIMessage(content="hi\ud83dthere", id="abc")
        result = _sanitize_agent_message({"messages": [msg]})
        self.assertIn("messages", result)
        new_msg = result["messages"][0]
        self.assertEqual(new_msg.content, "hi" + _REPL + "there")
        # Same id so add_messages reducer replaces in place rather than appending.
        self.assertEqual(new_msg.id, "abc")
        new_msg.content.encode("utf-8")  # must not raise

    def test_sanitizes_list_content_blocks(self):
        msg = AIMessage(
            content=[
                {"type": "text", "text": "clean part"},
                {"type": "text", "text": "dirty\ud83dpart"},
            ],
            id="xyz",
        )
        result = _sanitize_agent_message({"messages": [msg]})
        new_blocks = result["messages"][0].content
        self.assertEqual(new_blocks[0]["text"], "clean part")
        self.assertEqual(new_blocks[1]["text"], "dirty" + _REPL + "part")

    def test_sanitizes_tool_call_args(self):
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": "find\ud83dthis"},
                    "id": "call_1",
                }
            ],
            id="m1",
        )
        result = _sanitize_agent_message({"messages": [msg]})
        new_tcs = result["messages"][0].tool_calls
        self.assertEqual(new_tcs[0]["args"]["query"], "find" + _REPL + "this")
        # Untouched fields preserved.
        self.assertEqual(new_tcs[0]["name"], "search")
        self.assertEqual(new_tcs[0]["id"], "call_1")

    def test_sanitizes_both_content_and_tool_call_args(self):
        msg = AIMessage(
            content="reply\ud83d",
            tool_calls=[{"name": "f", "args": {"k": "v\udcff"}, "id": "c"}],
            id="m2",
        )
        result = _sanitize_agent_message({"messages": [msg]})
        new_msg = result["messages"][0]
        self.assertEqual(new_msg.content, "reply" + _REPL)
        self.assertEqual(new_msg.tool_calls[0]["args"]["k"], "v" + _REPL)

    def test_only_last_message_inspected(self):
        # Earlier dirty messages must NOT be touched (already passed through hook
        # in a prior turn). Hook only sees the freshly-produced message.
        dirty_old = AIMessage(content="old\ud83d", id="old")
        clean_new = AIMessage(content="new clean", id="new")
        result = _sanitize_agent_message({"messages": [dirty_old, clean_new]})
        self.assertEqual(result, {})

    def test_sanitizes_invalid_tool_calls(self):
        msg = AIMessage(
            content="",
            invalid_tool_calls=[
                {
                    "name": "search",
                    "args": "raw\ud83djson",  # parse failure leaves args as raw str
                    "id": "bad_1",
                    "error": "JSONDecodeError: bad\udcffsurrogate",
                }
            ],
            id="m_inv",
        )
        result = _sanitize_agent_message({"messages": [msg]})
        new_itcs = result["messages"][0].invalid_tool_calls
        self.assertEqual(new_itcs[0]["args"], "raw" + _REPL + "json")
        self.assertEqual(new_itcs[0]["error"], "JSONDecodeError: bad" + _REPL + "surrogate")

    def test_sanitizes_additional_kwargs(self):
        # Some providers stash raw response bits under additional_kwargs
        # (legacy function_call shape, refusal text, reasoning, etc.).
        msg = AIMessage(
            content="ok",
            additional_kwargs={
                "refusal": "I won't\ud83d",
                "reasoning": {"text": "step\udcff one"},
            },
            id="m_ak",
        )
        result = _sanitize_agent_message({"messages": [msg]})
        new_ak = result["messages"][0].additional_kwargs
        self.assertEqual(new_ak["refusal"], "I won't" + _REPL)
        self.assertEqual(new_ak["reasoning"]["text"], "step" + _REPL + " one")


class HookReducerIntegrationTests(unittest.TestCase):
    """Verify the hook output composes correctly with LangGraph's add_messages."""

    def test_replaces_last_message_in_place(self):
        # Same id → reducer must REPLACE, not append. Length stays the same,
        # last id matches, content is sanitized.
        original = [
            HumanMessage(content="please search", id="h1"),
            AIMessage(content="dirty\ud83dreply", id="a1"),
        ]
        hook_out = _sanitize_agent_message({"messages": original})
        merged = add_messages(original, hook_out["messages"])

        self.assertEqual(len(merged), 2, "reducer appended instead of replacing")
        self.assertEqual(merged[-1].id, "a1")
        self.assertEqual(merged[-1].content, "dirty" + _REPL + "reply")
        merged[-1].content.encode("utf-8")  # must not raise

    def test_clean_message_yields_no_reducer_change(self):
        original = [AIMessage(content="all clean", id="a2")]
        hook_out = _sanitize_agent_message({"messages": original})
        # Hook returns {} → nothing for the reducer to merge.
        self.assertEqual(hook_out, {})
        merged = add_messages(original, hook_out.get("messages", []))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[-1].content, "all clean")


if __name__ == "__main__":
    unittest.main()
