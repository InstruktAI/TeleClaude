#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic", "openai"]
# ///
"""Background summarizer - generates AI summary and sends to MCP socket."""

import json
import os
import subprocess
import sys
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI


def generate_summary(transcript: str) -> str:
    """Generate summary using Claude API (with OpenAI fallback)."""
    # Try Anthropic first
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:

            client = Anthropic(api_key=anthropic_key)

            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=150,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Summarize what was accomplished in this Claude Code session in 1-2 sentences. Focus on the main outcome/deliverable.

Transcript:
{transcript[:8000]}""",
                    }
                ],
            )

            summary_text = response.content[0].text
            return f"Work complete! {summary_text}"

        except:
            pass  # Fall through to OpenAI

    # Try OpenAI as fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:

            client = OpenAI(api_key=openai_key)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=150,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Summarize what was accomplished in this Claude Code session in 1-2 sentences. Focus on the main outcome/deliverable.

Transcript:
{transcript[:8000]}""",
                    }
                ],
            )

            summary_text = response.choices[0].message.content
            return f"Work complete! {summary_text}"

        except:
            pass  # Fall through

    return "Work complete!"


def main() -> None:
    """Generate summary and send via MCP socket."""
    if len(sys.argv) != 3:
        sys.exit(1)

    session_id = sys.argv[1]
    transcript_path = sys.argv[2]

    try:
        # Read transcript
        transcript = Path(transcript_path).read_text()

        # Generate summary using Claude API
        summary = generate_summary(transcript)

        # Pipe to mcp_send.py
        hooks_dir = Path(__file__).parent
        mcp_send = hooks_dir / "scripts" / "mcp_send.py"

        payload = json.dumps({"session_id": session_id, "message": summary})
        subprocess.run(
            ["uv", "run", "--quiet", str(mcp_send)],
            input=payload,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    except:
        pass  # Fail silently


if __name__ == "__main__":
    main()
