"""qlw CLI entry point — dispatches to per-module register/main pairs."""
from __future__ import annotations

import argparse

from quant_llm_wiki import enrich, embed, sync
from quant_llm_wiki.ingest import wechat
from quant_llm_wiki.query import brainstorm
from quant_llm_wiki.agent import cli as agent_cli


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="qlw")
    sub = parser.add_subparsers(dest="cmd", required=True)

    wechat.register(sub.add_parser("ingest", help="Ingest WeChat articles or HTML files."))
    enrich.register(sub.add_parser("enrich", help="Enrich raw articles with LLM-generated metadata."))
    embed.register(sub.add_parser("embed", help="Build/update the ChromaDB vector index."))
    sync.register(sub.add_parser("sync", help="Move articles based on frontmatter status."))
    brainstorm.register_ask(sub.add_parser("ask", help="RAG Q&A over the knowledge base."))
    brainstorm.register_brainstorm(sub.add_parser("brainstorm", help="Generate brainstorm ideas with Rethink validation."))
    agent_cli.register(sub.add_parser("agent", help="Run the LangGraph agent (interactive or one-shot)."))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
