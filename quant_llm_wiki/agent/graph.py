from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from quant_llm_wiki.agent.prompts import SYSTEM_PROMPT
from quant_llm_wiki.agent.tools import ALL_TOOLS
from quant_llm_wiki.shared import get_llm_config


def create_agent():
    """Create and return a compiled LangGraph ReAct agent.

    Uses the OpenAI-compatible API configured via LLM_* or ZHIPU_* env vars.
    Works with any provider: Zhipu GLM, DeepSeek, Moonshot, Qwen, OpenAI, etc.
    """
    try:
        api_key, base_url, model = get_llm_config()
    except RuntimeError as exc:
        raise RuntimeError(
            f"Failed to initialize agent LLM: {exc}\n"
            f"Configure via .env file or environment variables. "
            f"See llm_config.example.env for examples."
        ) from exc

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
    )

    agent = create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )
    return agent
