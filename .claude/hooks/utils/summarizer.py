#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic", "openai"]
# ///
"""Pure summarizer utility - generates summary and title from transcript.

Input: transcript_path as argv[1]
Output: JSON to stdout {"summary": "...", "title": "..."}

This utility knows NOTHING about TeleClaude, MCP, or messaging.
It's a pure text-in/JSON-out processor.
"""

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI


def generate_summary_and_title(transcript: str) -> tuple[str, str | None]:
    """Generate summary and title using Claude API (with OpenAI fallback).

    Returns:
        Tuple of (summary_message, title) where title may be None if extraction fails.
    """
    prompt = f"""Analyze this Claude Code session and provide:
1. A 1-2 sentence summary of what was accomplished (focus on main outcome/deliverable)
2. A short title (max 50 chars) describing the work done

Format your response EXACTLY as:
SUMMARY: <your summary>
TITLE: <short title>

Transcript:
{transcript[:8000]}"""

    # Try Anthropic first
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            client = Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_response(response.content[0].text)
        except Exception:
            pass  # Fall through to OpenAI

    # Try OpenAI as fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_response(response.choices[0].message.content or "")
        except Exception:
            pass  # Fall through to default

    return "Work complete!", None


def _parse_response(text: str) -> tuple[str, str | None]:
    """Parse LLM response into summary and title."""
    summary = "Work complete!"
    title = None

    for line in text.strip().split("\n"):
        if line.startswith("SUMMARY:"):
            summary = f"Work complete! {line[8:].strip()}"
        elif line.startswith("TITLE:"):
            title = line[6:].strip()[:50]  # Max 50 chars

    return summary, title


def main() -> int:
    """Read transcript, generate summary/title, output JSON to stdout."""
    if len(sys.argv) != 2:
        print(json.dumps({"error": f"Usage: {sys.argv[0]} <transcript_path>"}))
        return 1

    transcript_path = sys.argv[1]

    if not Path(transcript_path).exists():
        print(json.dumps({"error": f"Transcript not found: {transcript_path}"}))
        return 1

    transcript = Path(transcript_path).read_text()
    summary, title = generate_summary_and_title(transcript)

    # Output JSON to stdout - the ONLY output contract
    print(json.dumps({"summary": summary, "title": title}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
