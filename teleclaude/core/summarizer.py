"""Summary utilities for agent stop payloads."""

import json
import os
from collections.abc import Callable
from typing import Any, cast

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema

SUMMARY_MODEL_ANTHROPIC = "claude-haiku-4-5-20251001"
SUMMARY_MODEL_OPENAI = "gpt-5-nano-2025-08-07"
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
1. **summary** (max {max_summary_words} words): Write as the assistant in first person, describing what you did. Omit strange strings. such as UUIDs etc. If trivial or very short, return verbatim.
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


async def _call_summarizer(
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema shape is dynamic.
    parser: Callable[[str], Any],
) -> Any:
    """Call the summarizer API with the given prompt."""

    errors: list[str] = []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            anthropic_client = AsyncAnthropic(api_key=api_key)
            response = await anthropic_client.beta.messages.create(
                model=SUMMARY_MODEL_ANTHROPIC,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
                betas=["structured-outputs-2025-11-13"],
                output_format={
                    "type": "json_schema",
                    "schema": {
                        "type": schema["type"],
                        "properties": schema["properties"],
                        "required": schema["required"],
                        "additionalProperties": schema["additionalProperties"],
                    },
                },
            )
            text = response.content[0].text  # type: ignore[union-attr]
            return parser(text)
        except Exception as e:
            errors.append(f"Anthropic: {e}")

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            openai_client = AsyncOpenAI(api_key=openai_key)
            response_format: ResponseFormatJSONSchema = {
                "type": "json_schema",
                "json_schema": {
                    "name": "summary",
                    "schema": schema,
                    "strict": True,
                },
            }
            response = await openai_client.chat.completions.create(
                model=SUMMARY_MODEL_OPENAI,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
                response_format=response_format,
            )
            response_any = cast(Any, response)
            text = response_any.choices[0].message.content or ""
            return parser(text)
        except Exception as e:
            errors.append(f"OpenAI: {e}")

    if errors:
        raise RuntimeError(f"All summarizers failed: {'; '.join(errors)}")
    raise RuntimeError("No summarizer available (missing API key)")


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
