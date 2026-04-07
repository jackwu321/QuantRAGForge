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

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Knowledge base agent CLI")
    parser.add_argument("--query", help="Single query to run (non-interactive mode)")
    return parser.parse_args()


def run_query(agent, query: str) -> str:
    """Run a single query through the agent and return the final response."""
    result = agent.invoke({"messages": [{"role": "user", "content": query}]})
    messages = result["messages"]
    # Find the last AI message that is not a tool call
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai" and msg.content and not msg.tool_calls:
            return msg.content
        if hasattr(msg, "type") and msg.type == "ai" and msg.content:
            return msg.content
    return str(messages[-1].content) if messages else "No response."


def interactive_loop(agent) -> None:
    """Run an interactive multi-turn conversation."""
    print("Knowledge Base Agent (type 'quit' or 'exit' to stop)")
    print("-" * 50)
    messages: list[dict] = []
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

        messages.append({"role": "user", "content": user_input})
        try:
            result = agent.invoke({"messages": messages})
            messages = result["messages"]
            # Print the last AI response
            for msg in reversed(messages):
                if hasattr(msg, "type") and msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
                    print(f"\nAgent: {msg.content}")
                    break
            else:
                if messages:
                    print(f"\nAgent: {messages[-1].content}")
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break
        except Exception as exc:
            print(f"\nError ({type(exc).__name__}): {exc}")


def main() -> int:
    args = parse_args()

    from agent import create_agent

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


if __name__ == "__main__":
    raise SystemExit(main())
