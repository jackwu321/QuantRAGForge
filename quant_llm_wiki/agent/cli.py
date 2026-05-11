#!/usr/bin/env python3
"""CLI entry point for the knowledge base agent.

Usage:
    # Interactive multi-turn conversation
    python3 agent_cli.py

    # Single command
    python3 agent_cli.py --query "list all articles"
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from langchain_core.messages import HumanMessage

from quant_llm_wiki.shared import _sanitize_lone_surrogates


def _safe_text(value: Any) -> str:
    """Coerce to str and strip lone surrogates so print/encode never crashes.

    Why: defense in depth at the output boundary — the agent's `post_model_hook`
    and `post_llm_json` already clean upstream, but nothing stops a stray
    surrogate from arriving here via a tool message, exception repr, etc.
    """
    text = value if isinstance(value, str) else str(value)
    return _sanitize_lone_surrogates(text)


def _extract_last_ai_content(messages) -> str:
    """Extract the last AI message content that isn't a pure tool call."""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
            return msg.content
        if hasattr(msg, "type") and msg.type == "ai" and msg.content:
            return msg.content
    return str(messages[-1].content) if messages else "No response."


def run_query(agent, query: str) -> str:
    """Run a single query through the agent, streaming intermediate output."""
    messages = []
    for state in agent.stream(
        {"messages": [{"role": "user", "content": query}]},
        stream_mode="values",
    ):
        messages = state.get("messages", messages)
    return _extract_last_ai_content(messages)


def interactive_loop(agent) -> None:
    """Run an interactive multi-turn conversation."""
    print("Knowledge Base Agent (type 'quit' or 'exit' to stop)")
    print("-" * 50)
    messages: list = []
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        messages.append(HumanMessage(content=user_input))
        try:
            for state in agent.stream(
                {"messages": messages},
                stream_mode="values",
            ):
                messages = state.get("messages", messages)
            print(f"\nAgent: {_safe_text(_extract_last_ai_content(messages))}")
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break
        except Exception as exc:
            print(_safe_text(f"\nError ({type(exc).__name__}): {exc}"))


def register(parser: argparse.ArgumentParser) -> None:
    """Attach this module's CLI flags to `parser`. Called by quant_llm_wiki.cli."""
    parser.add_argument("--query", help="Single query to run (non-interactive mode)")
    parser.set_defaults(func=_run)


def run_agent(query: str | None = None) -> int:
    """Run the LangGraph agent interactively or with a single query."""
    from quant_llm_wiki.agent import create_agent

    agent = create_agent()
    if query:
        try:
            print(_safe_text(run_query(agent, query)))
        except Exception as exc:
            print(_safe_text(f"Error ({type(exc).__name__}): {exc}"), file=sys.stderr)
            return 1
        return 0
    interactive_loop(agent)
    return 0


def _run(args) -> int:
    return run_agent(args.query)


def main() -> int:
    """Standalone entry: python -m quant_llm_wiki.agent.cli ..."""
    parser = argparse.ArgumentParser(description="Knowledge base agent CLI")
    register(parser)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
