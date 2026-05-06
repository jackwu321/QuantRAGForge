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
from pathlib import Path

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge base agent CLI")
    parser.add_argument("--query", help="Single query to run (non-interactive mode)")
    return parser.parse_args()


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
            response = _extract_last_ai_content(messages)
            print(f"\nAgent: {response}")
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break
        except Exception as exc:
            print(f"\nError ({type(exc).__name__}): {exc}")


def register(parser: argparse.ArgumentParser) -> None:
    """Attach this module's CLI flags to `parser`. Called by quant_llm_wiki.cli."""
    parser.add_argument("--query", help="Single query to run (non-interactive mode)")
    parser.set_defaults(func=_run)


def _run(args) -> int:
    """The module's command body. Receives parsed args from the dispatcher."""
    from quant_llm_wiki.agent import create_agent

    agent = create_agent()

    if args.query:
        try:
            response = run_query(agent, args.query)
            print(response)
        except Exception as exc:
            print(f"Error ({type(exc).__name__}): {exc}", file=sys.stderr)
            return 1
        return 0

    interactive_loop(agent)
    return 0


def main() -> int:
    """Standalone entry: python -m quant_llm_wiki.agent.cli ..."""
    parser = argparse.ArgumentParser(description="Knowledge base agent CLI")
    register(parser)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
