"""Summary utilities for agent stop payloads."""

import json
import os
from pathlib import Path
from typing import Any, cast

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema

from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import extract_last_agent_message

SUMMARY_MODEL_ANTHROPIC = "claude-haiku-4-5-20251001"
SUMMARY_MODEL_OPENAI = "gpt-5-nano-2025-08-07"
SUMMARY_SCHEMA: dict[str, object] = {  # noqa: loose-dict - JSON schema definition
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "title": {"type": "string"},
    },
    "required": ["summary", "title"],
    "additionalProperties": False,
}


def _build_user_input_prompt(user_input: str, max_summary_words: int) -> str:
    """Build prompt for summarizing user input."""
    return f"""Summarize this user request.

## User Input:
{user_input}

## Output:
1. **title** (max 7 words, max 70 chars): What the user wants. Use imperative form (e.g., "Fix login bug", "Add dark mode").
2. **summary** (max {max_summary_words} words): Summarize the user's request. If trivial or very short, return verbatim.
"""


def _build_agent_output_prompt(agent_output: str, max_summary_words: int) -> str:
    """Build prompt for summarizing agent output."""
    return f"""Summarize this assistant response.

## Agent Output:
{agent_output}

## Output:
1. **title** (max 7 words, max 70 chars): What was accomplished. Use past tense (e.g., "Fixed login bug", "Added dark mode").
2. **summary** (max {max_summary_words} words): Write as the assistant in first person, describing what you did. Start with "I". If trivial or very short, return verbatim.
"""


async def summarize_user_input(user_input: str) -> tuple[str | None, str]:
    """Summarize user input. Returns (title, summary)."""
    if not user_input:
        raise ValueError("Empty user input")
    max_summary_words = config.summarizer.max_summary_words
    prompt = _build_user_input_prompt(user_input, max_summary_words)
    return await _call_summarizer(prompt)


async def summarize_agent_output(agent_output: str) -> tuple[str | None, str]:
    """Summarize agent output. Returns (title, summary)."""
    if not agent_output:
        raise ValueError("Empty agent output")
    max_summary_words = config.summarizer.max_summary_words
    prompt = _build_agent_output_prompt(agent_output, max_summary_words)
    return await _call_summarizer(prompt)


async def _call_summarizer(prompt: str) -> tuple[str | None, str]:
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
                        "type": SUMMARY_SCHEMA["type"],
                        "properties": SUMMARY_SCHEMA["properties"],
                        "required": SUMMARY_SCHEMA["required"],
                        "additionalProperties": SUMMARY_SCHEMA["additionalProperties"],
                    },
                },
            )
            text = response.content[0].text  # type: ignore[union-attr]
            return _parse_response(text)
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
                    "schema": SUMMARY_SCHEMA,
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
            return _parse_response(text)
        except Exception as e:
            errors.append(f"OpenAI: {e}")

    if errors:
        raise RuntimeError(f"All summarizers failed: {'; '.join(errors)}")
    raise RuntimeError("No summarizer available (missing API key)")


async def summarize(agent_name: AgentName, transcript_path: str) -> tuple[str | None, str, str | None]:
    """Summarize an agent session transcript."""
    if not Path(transcript_path).expanduser().exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    raw_transcript = extract_last_agent_message(transcript_path, agent_name, 1)
    if not raw_transcript:
        raise ValueError("Empty transcript")

    title, summary = await summarize_agent_output(raw_transcript)
    return title, summary, raw_transcript


# Backwards compatibility alias
summarize_text = summarize_agent_output


def _parse_response(text: str) -> tuple[str | None, str]:
    data = json.loads(text.strip())
    summary_value = data["summary"]
    title_value = data.get("title")
    summary = str(summary_value).strip()
    title = str(title_value).strip()[:70] if title_value else None
    if not summary:
        raise ValueError("Summary missing in model response")
    return title, summary
