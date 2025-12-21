"""Summary utilities for agent stop payloads."""

import json
import os
from typing import Any, cast

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import parse_session_transcript

SUMMARY_MODEL_ANTHROPIC = "claude-haiku-4-5-20251001"
SUMMARY_MODEL_OPENAI = "gpt-5-nano-2025-08-07"
SUMMARY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "title": {"type": "string"},
    },
    "required": ["summary", "title"],
    "additionalProperties": False,
}


async def summarize(agent_name: AgentName, transcript_path: str) -> tuple[str | None, str]:
    """Summarize an agent session transcript and return (title, summary)."""
    transcript = parse_session_transcript(
        transcript_path,
        title="",
        agent_name=agent_name,
        tail_chars=UI_MESSAGE_MAX_CHARS,
    )
    if transcript.startswith("Transcript file not found:") or transcript.startswith("Error parsing transcript:"):
        raise ValueError(transcript)

    prompt = f"""Summarize what an AI assistant reported in its recent transcript. Write for humans tracking progress.

Rules:
- First person (\"I...\")
- 1-2 sentences
- Accurately reflect what the AI said it did or observed
- Preserve the subject
- Also provide a short title (max 50 chars)

Transcript:
{transcript}"""

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
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

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
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

    raise RuntimeError("No summarizer available (missing API key)")


def _parse_response(text: str) -> tuple[str | None, str]:
    data = json.loads(text.strip())
    summary_value = data["summary"]
    title_value = data.get("title")
    summary = str(summary_value).strip()
    title = str(title_value).strip()[:50] if title_value else None
    if not summary:
        raise ValueError("Summary missing in model response")
    return title, summary
