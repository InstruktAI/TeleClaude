"""Summary utilities for agent stop payloads."""

import json
import os
from collections.abc import Callable
from typing import Any

from teleclaude.config import config
from teleclaude.services.summarizer_backends import summarize_anthropic, summarize_openai_compatible

# Dateless model aliases so summaries track each provider's latest without config churn.
_DEFAULT_MODELS = {"openai": "gpt-5-nano", "anthropic": "claude-haiku-4-5", "google": "gemini-2.5-flash"}
# Gemini's OpenAI-compatible endpoint lets the google provider reuse the openai client.
_GOOGLE_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Local OpenAI-compatible servers (LM Studio) ignore the key but the SDK requires one.
_LOCAL_API_KEY_FALLBACK = "lm-studio"
TITLE_SCHEMA: dict[str, object] = {  # guard: loose-dict - JSON schema definition
    "type": "object",
    "properties": {
        "title": {"type": "string"},
    },
    "required": ["title"],
    "additionalProperties": False,
}
SUMMARY_SCHEMA: dict[str, object] = {  # guard: loose-dict - JSON schema definition
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
    },
    "required": ["summary"],
    "additionalProperties": False,
}


def _build_session_title_prompt(recent_turns: list[tuple[str, str]]) -> str:
    """Build prompt for generating a title from recent session turns."""
    formatted_turns = "\n\n".join(f"{role.title()}: {text}" for role, text in recent_turns)
    return f"""Generate a concise title for this session.

Base the title on the enduring user intent across the recent conversation, not
transient operational chatter such as run commands, model changes, or status noise.

## Recent Conversation:
{formatted_turns}

## Output:
1. **title** (max 7 words, max 70 chars): What the session is about. Prefer imperative phrasing when it fits.
"""


def _build_agent_output_summary_prompt(agent_output: str, max_summary_words: int) -> str:
    """Build prompt for summarizing agent output."""
    return f"""Summarize this assistant response.

## Agent Output:
{agent_output}

## Output:
1. **summary** (max {max_summary_words} words): Capture what actually happened in this turn.
   Use first person only when the agent performed concrete actions. For monitoring, waiting,
   or status reporting, use natural phrasing (e.g. "Monitoring workers", "Waiting on build
   results"). Omit UUIDs and opaque strings. If trivial or very short, return verbatim.
"""


async def generate_session_title(recent_turns: list[tuple[str, str]]) -> str | None:
    """Generate a session title from recent transcript turns."""
    if not recent_turns:
        raise ValueError("Empty session title context")
    prompt = _build_session_title_prompt(recent_turns)
    return await _call_title_summarizer(prompt)


async def summarize_agent_output(agent_output: str) -> tuple[str | None, str]:
    """Summarize agent output. Returns (None, summary)."""
    if not agent_output or not agent_output.strip():
        raise ValueError("Empty agent output")
    max_summary_words = 30
    prompt = _build_agent_output_summary_prompt(agent_output, max_summary_words)
    summary = await _call_summary_summarizer(prompt)
    return None, summary


def _provider_api_key(provider: str) -> str | None:
    return {
        "anthropic": os.getenv("ANTHROPIC_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
        "google": os.getenv("GOOGLE_API_KEY"),
    }.get(provider)


def _summarizer_model(provider: str) -> str:
    configured = config.summarizer.models.get(provider) if config.summarizer else None
    return configured or _DEFAULT_MODELS[provider]


async def _call_summarizer(
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema shape is dynamic.
    parser: Callable[[str], Any],
) -> Any:
    """Summarize via the configured providers in order, skipping ones without a key.

    The local OpenAI-compatible provider (e.g. LM Studio) is tried first when
    enabled; then each cloud provider in ``provider_priority`` is tried, silently
    skipped when its API key is absent.
    """
    summ = config.summarizer
    errors: list[str] = []

    if summ and summ.local.enabled and summ.local.base_url and summ.local.model:
        try:
            return await summarize_openai_compatible(
                prompt,
                schema,
                parser,
                base_url=summ.local.base_url,
                api_key=os.getenv("SUMMARIZER_LOCAL_API_KEY", _LOCAL_API_KEY_FALLBACK),
                model=summ.local.model,
            )
        except Exception as e:
            errors.append(f"local: {e}")

    priority = summ.provider_priority if (summ and summ.provider_priority) else ["openai", "anthropic", "google"]
    for provider in priority:
        api_key = _provider_api_key(provider)
        if not api_key:
            continue  # silent skip — provider not configured
        try:
            if provider == "anthropic":
                return await summarize_anthropic(
                    prompt, schema, parser, api_key=api_key, model=_summarizer_model("anthropic")
                )
            base_url = _GOOGLE_OPENAI_BASE_URL if provider == "google" else None
            return await summarize_openai_compatible(
                prompt, schema, parser, base_url=base_url, api_key=api_key, model=_summarizer_model(provider)
            )
        except Exception as e:
            errors.append(f"{provider}: {e}")

    if errors:
        raise RuntimeError(f"All summarizers failed: {'; '.join(errors)}")
    raise RuntimeError("No summarizer available (no provider key found)")


async def _call_title_summarizer(prompt: str) -> str | None:
    return await _call_summarizer(prompt, TITLE_SCHEMA, _parse_title_response)  # type: ignore[no-any-return]


async def _call_summary_summarizer(prompt: str) -> str:
    return await _call_summarizer(prompt, SUMMARY_SCHEMA, _parse_summary_response)  # type: ignore[no-any-return]


def _parse_title_response(text: str) -> str | None:
    data = json.loads(text.strip())
    title_value = data.get("title")
    title = str(title_value).strip()[:70] if title_value else None
    if not title:
        raise ValueError("Title missing in model response")
    return title


def _parse_summary_response(text: str) -> str:
    data = json.loads(text.strip())
    summary_value = data["summary"]
    summary = str(summary_value).strip()
    if not summary:
        raise ValueError("Summary missing in model response")
    return summary
