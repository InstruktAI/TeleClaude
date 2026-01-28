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


async def summarize(agent_name: AgentName, transcript_path: str) -> tuple[str | None, str, str | None]:
    """Summarize an agent session transcript.

    Returns:
        Tuple of (title, summary, raw_transcript) where:
        - title: Short description of user's intent (max 70 chars)
        - summary: LLM-generated summary of what the agent did
        - raw_transcript: The last agent text message, or None if not found
    """
    # Verify file exists
    if not Path(transcript_path).expanduser().exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    # Extract last agent text message for both storage and LLM input.
    raw_transcript = extract_last_agent_message(transcript_path, agent_name, 1)
    if not raw_transcript:
        raise ValueError("Empty transcript")

    # Build prompt with configurable constraints
    max_summary_words = config.summarizer.max_summary_words

    prompt = f"""Analyze this AI assistant session to generate a title and summary.

## Latest Agent Output:
{raw_transcript}

## Output:
1. **title** (max 7 words, max 70 chars): What the USER is trying to accomplish. Focus on user intent, not agent actions. Use imperative form (e.g., "Fix login bug", "Add dark mode").
2. **summary** (max {max_summary_words} words, first person "I..."): Summarize the text above. If it is trivial or very short, return it verbatim.
"""

    errors: list[str] = []

    # Try Anthropic first
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
            title, summary = _parse_response(text)
            return title, summary, raw_transcript
        except Exception as e:
            errors.append(f"Anthropic: {e}")

    # Fallback to OpenAI
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
            title, summary = _parse_response(text)
            return title, summary, raw_transcript
        except Exception as e:
            errors.append(f"OpenAI: {e}")

    if errors:
        raise RuntimeError(f"All summarizers failed: {'; '.join(errors)}")
    raise RuntimeError("No summarizer available (missing API key)")


def _parse_response(text: str) -> tuple[str | None, str]:
    data = json.loads(text.strip())
    summary_value = data["summary"]
    title_value = data.get("title")
    summary = str(summary_value).strip()
    title = str(title_value).strip()[:70] if title_value else None
    if not summary:
        raise ValueError("Summary missing in model response")
    return title, summary
