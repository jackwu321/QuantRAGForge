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


def run_query(agent, query: str, session=None) -> str:
    """Run a single query through the agent, streaming intermediate output."""
    if session:
        session.on_user_prompt(query)
    messages = []
    for state in agent.stream(
        {"messages": [{"role": "user", "content": query}]},
        stream_mode="values",
    ):
        messages = state.get("messages", messages)
    if session:
        session.observe_messages(messages, 0)
    return _extract_last_ai_content(messages)


def interactive_loop(agent, session=None) -> None:
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
        if session:
            session.on_user_prompt(user_input)
        seen = len(messages)
        try:
            for state in agent.stream(
                {"messages": messages},
                stream_mode="values",
            ):
                messages = state.get("messages", messages)
            if session:
                session.observe_messages(messages, seen)
            print(f"\nAgent: {_safe_text(_extract_last_ai_content(messages))}")
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break
        except Exception as exc:
            print(_safe_text(f"\nError ({type(exc).__name__}): {exc}"))


def register(parser: argparse.ArgumentParser) -> None:
    """Attach this module's CLI flags to `parser`. Called by quant_llm_wiki.cli."""
    parser.add_argument("--query", help="Single query to run (non-interactive mode)")
    parser.add_argument("--thread", help="Switch to/create a named memory thread.")
    parser.add_argument("--new", action="store_true",
                        help="Fork a fresh date-stamped memory thread.")
    parser.add_argument("--summary", action="store_true",
                        help="Run the LLM session summarizer at session end.")
    parser.add_argument("--no-memory", action="store_true",
                        help="Disable workflow memory entirely (stateless run).")
    parser.set_defaults(func=_run)


def run_agent(query: str | None = None, thread: str | None = None,
              new_thread: bool = False, want_summary: bool = False,
              no_memory: bool = False) -> int:
    """Run the LangGraph agent interactively or with a single query."""
    from quant_llm_wiki.agent import create_agent
    from quant_llm_wiki.paths import resolve_kb_root
    from quant_llm_wiki.shared import get_memory_config

    mem_cfg = get_memory_config()
    session = None
    if not no_memory and mem_cfg["enabled"]:
        from quant_llm_wiki.agent.memory.hooks import MemorySession

        session = MemorySession.start(
            resolve_kb_root(None), thread=thread, new_thread=new_thread,
            want_summary=want_summary or mem_cfg["auto_summary"])

    memory_tools = None
    preamble = None
    if session:
        from quant_llm_wiki.agent.memory.tools import MEMORY_TOOLS

        memory_tools = MEMORY_TOOLS
        preamble = session.preamble() or None

    agent = create_agent(memory_tools=memory_tools, preamble=preamble)
    try:
        if query:
            try:
                print(_safe_text(run_query(agent, query, session=session)))
            except Exception as exc:
                print(_safe_text(f"Error ({type(exc).__name__}): {exc}"), file=sys.stderr)
                return 1
            return 0
        interactive_loop(agent, session=session)
        return 0
    finally:
        if session:
            session.on_session_end()


def _run(args) -> int:
    return run_agent(args.query, thread=args.thread, new_thread=args.new,
                     want_summary=args.summary, no_memory=args.no_memory)


def main() -> int:
    """Standalone entry: python -m quant_llm_wiki.agent.cli ..."""
    parser = argparse.ArgumentParser(description="Knowledge base agent CLI")
    register(parser)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
