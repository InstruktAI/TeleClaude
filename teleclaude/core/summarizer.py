"""Summary utilities for agent stop payloads."""

import json
import os
from pathlib import Path
from typing import Any, cast

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import (
    _iter_claude_entries,
    _iter_codex_entries,
    _iter_gemini_entries,
    parse_session_transcript,
)

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


def extract_recent_exchanges(
    transcript_path: str,
    agent_name: AgentName,
    n_exchanges: int = 2,
) -> str:
    """Extract last N user messages with their text-only agent responses.

    guard: allow-string-compare
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return ""

    if agent_name == AgentName.CLAUDE:
        entries = _iter_claude_entries(path)
    elif agent_name == AgentName.CODEX:
        entries = _iter_codex_entries(path)
    elif agent_name == AgentName.GEMINI:
        entries = _iter_gemini_entries(path)
    else:
        return ""

    exchanges: list[dict[str, str]] = []

    for entry in entries:
        message = entry.get("message")
        # Handle response_item payload wrapper
        if not isinstance(message, dict) and entry.get("type") == "response_item":
            payload = entry.get("payload")
            if isinstance(payload, dict):
                message = payload

        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = message.get("content")

        if role == "user":
            user_text = ""
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                texts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") in ("input_text", "text"):
                        texts.append(str(block.get("text", "")))
                user_text = "\n".join(texts)

            exchanges.append({"user": user_text, "assistant": ""})

        elif role == "assistant":
            if not exchanges:
                continue

            assistant_text = ""
            if isinstance(content, str):
                assistant_text = content
            elif isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(str(block.get("text", "")))
                assistant_text = "\n".join(texts)

            if assistant_text:
                if exchanges[-1]["assistant"]:
                    exchanges[-1]["assistant"] += "\n" + assistant_text
                else:
                    exchanges[-1]["assistant"] = assistant_text

    # Take last N exchanges
    recent = exchanges[-n_exchanges:]

    # Format output
    output_lines = []
    for ex in recent:
        output_lines.append(f"User: {ex['user']}")
        if ex["assistant"]:
            output_lines.append(f"Assistant: {ex['assistant']}")
        output_lines.append("")

    return "\n".join(output_lines).strip()


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

    recent_exchanges = extract_recent_exchanges(transcript_path, agent_name)

    prompt = f"""Analyze this AI assistant session to generate a title and summary.

## Recent Exchanges (User intent context):
{recent_exchanges}

## Latest Agent Output (Execution details):
{transcript}

## Output:
1. **title** (max 7 words, max 70 chars): What the USER is trying to accomplish. Focus on user intent, not agent actions. Use imperative form (e.g., "Fix login bug", "Add dark mode").
2. **summary** (1-2 sentences, first person "I..."): What the agent just did based on its responses above.
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
            return _parse_response(text)
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
            return _parse_response(text)
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
