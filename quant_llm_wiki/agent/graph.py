from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from quant_llm_wiki.agent.prompts import SYSTEM_PROMPT
from quant_llm_wiki.agent.tools import ALL_TOOLS
from quant_llm_wiki.shared import _sanitize_response_strings, get_llm_config

# AIMessage fields that may carry provider-emitted strings and therefore can
# transport lone UTF-16 surrogates. We deliberately skip `response_metadata`
# (model name / finish reason / token counts — low-risk, rarely user-visible)
# and `usage_metadata` (numeric).
_SANITIZED_FIELDS = ("content", "tool_calls", "invalid_tool_calls", "additional_kwargs")


def _sanitize_agent_message(state: dict[str, Any]) -> dict[str, Any]:
    """Strip lone UTF-16 surrogates from the most recent AIMessage.

    Why: ChatOpenAI bypasses our `post_llm_json` sanitizer, so any surrogate
    halves emitted by the provider would reach LangGraph's stream/print path
    and crash on UTF-8 encode. Returning a copy of the same message (same id)
    causes the `add_messages` reducer to replace it in place rather than
    appending a duplicate.

    Scope: only AIMessage. Tool outputs (ToolMessage) come from our own tool
    code — if a tool ever returned surrogate-bearing text, the output-boundary
    `_safe_text` in `agent/cli.py` catches it on print. Sanitizing ToolMessage
    in the hook would shift framework-internal state for a contingency we
    don't actually have a producer for.
    """
    messages = state.get("messages") or []
    if not messages:
        return {}
    last = messages[-1]
    if not isinstance(last, AIMessage):
        return {}

    update: dict[str, Any] = {}
    for field in _SANITIZED_FIELDS:
        original = getattr(last, field, None)
        if not original:
            continue
        cleaned = _sanitize_response_strings(original)
        if cleaned != original:
            update[field] = cleaned

    if not update:
        return {}

    return {"messages": [last.model_copy(update=update)]}


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
        post_model_hook=_sanitize_agent_message,
    )
    return agent
