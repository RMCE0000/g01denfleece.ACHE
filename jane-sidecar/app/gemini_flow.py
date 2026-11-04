"""LangChain Gemini flow for Jane's live conversation turns."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableBranch, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

gemini_override: ContextVar = ContextVar("g01_gemini_override", default=None)

UNREACHABLE = "I could not reach Gemini."
_COMPLEX_TERMS = re.compile(
    r"\b(analy[sz]e|blueprint|calculate|compare|design|diagnose|evaluate|"
    r"multi-step|optimi[sz]e|organize|plan|prioritize|strategy|trade-?off)\b",
    re.I,
)


def chat_messages(system: str, user: str, history: list[dict] | None = None) -> list[BaseMessage]:
    """Preserve Jane/homesteader roles while keeping the constitution as system policy."""
    messages: list[BaseMessage] = [SystemMessage(content=system)]
    if not history:
        return [*messages, HumanMessage(content=user)]
    for line in history:
        content = str(line.get("content") or "").strip()
        if not content:
            continue
        speaker = str(line.get("speaker") or "").strip()
        if not speaker:
            speaker = "Jane" if line.get("role") == "jane" else "Homesteader"
        text = f"{speaker}: {content}"
        messages.append(AIMessage(content=text) if line.get("role") == "jane" else HumanMessage(content=text))
    return messages


def _latest_homesteader_text(user: str, history: list[dict] | None) -> str:
    for line in reversed(history or []):
        if line.get("role") != "jane":
            content = str(line.get("content") or "").strip()
            if content:
                return content
    return str(user or "").strip()


def task_complexity(user: str, history: list[dict] | None = None) -> str:
    """Use Pro only when the requested reasoning is materially more involved."""
    latest = _latest_homesteader_text(user, history)
    words = latest.split()
    if (
        len(latest) >= 600
        or len(words) >= 100
        or latest.count("?") >= 2
        or len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", latest)) >= 2
        or _COMPLEX_TERMS.search(latest)
    ):
        return "complex"
    return "standard"


def _model(
    settings: Settings,
    model_name: str,
    *,
    max_tokens: int,
    thinking_level: str,
) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model_name,
        api_key=settings.gemini_api_key,
        temperature=0.2,
        max_tokens=max_tokens,
        thinking_level=thinking_level,
        retries=2,
        request_timeout=90,
    )


def build_gemini_chain(settings: Settings):
    """Route one shared LangChain message flow to Flash or Pro."""
    messages = RunnableLambda(lambda state: state["messages"])
    flash = messages | _model(
        settings,
        settings.gemini_chat_model,
        max_tokens=1000,
        thinking_level="minimal",
    ) | StrOutputParser()
    pro = messages | _model(
        settings,
        settings.gemini_deliberation_model,
        max_tokens=3000,
        thinking_level="high",
    ) | StrOutputParser()
    return RunnableBranch(
        (lambda state: state["complexity"] == "complex", pro),
        flash,
    )


async def complete_text(system: str, user: str, history: list[dict] | None = None) -> str:
    settings = get_settings()
    complexity = task_complexity(user, history)
    model_name = settings.gemini_deliberation_model if complexity == "complex" else settings.gemini_chat_model
    messages = chat_messages(system, user, history)
    override = gemini_override.get()
    if override is not None:
        result = override(model_name, messages, complexity)
        if hasattr(result, "__await__"):
            result = await result
        return str(result or "").strip() or UNREACHABLE
    if not settings.gemini_api_key:
        log.error("G01_GEMINI_API_KEY is not configured")
        return UNREACHABLE
    try:
        result = await build_gemini_chain(settings).ainvoke(
            {"messages": messages, "complexity": complexity}
        )
    except Exception:
        log.exception("Gemini did not answer Jane's %s turn", complexity)
        return UNREACHABLE
    return str(result or "").strip() or UNREACHABLE
