#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["anthropic", "openai"]
# ///
"""Background summarizer - generates AI summary and sends to MCP socket."""

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add parent directory to sys.path for imports when run as script
sys.path.insert(0, str(Path(__file__).parent))

from anthropic import Anthropic
from mcp_send import mcp_send
from openai import OpenAI

LOG_FILE = Path.cwd() / ".claude" / "hooks" / "logs" / "summarizer.log"


def log(message: str) -> None:
    """Write log message to file."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] {message}\n")
    except:
        pass


def generate_summary(transcript: str) -> str:
    """Generate summary using Claude API (with OpenAI fallback)."""
    log("Generating summary...")
    # Try Anthropic second
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            log("Trying Anthropic API...")
            client = Anthropic(api_key=anthropic_key)

            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=150,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"""You are the dev. Summarize what you accomplished in this Claude Code session in 1-2 sentences. Focus on the main outcome/deliverable.

Transcript:
{transcript[:8000]}"""
                        ),
                    }
                ],
            )

            summary_text = response.content[0].text
            log(f"Anthropic summary generated: {summary_text[:100]}...")
            return f"Work complete! {summary_text}"

        except Exception as e:
            log(f"Anthropic API failed: {str(e)}")

    # Try OpenAI as fallback
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            log("Trying OpenAI API...")
            client = OpenAI(api_key=openai_key)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=150,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"""Summarize what was accomplished in this Claude Code session in 1-2 sentences. Focus on the main outcome/deliverable.

Transcript:
{transcript[:8000]}"""
                        ),
                    }
                ],
            )

            summary_text = response.choices[0].message.content
            log(f"OpenAI summary generated: {summary_text[:100]}...")
            return f"Work complete! {summary_text}"

        except Exception as e:
            log(f"OpenAI API failed: {str(e)}")

    log("No API key available, using default message")
    return "Work complete!"


def main() -> None:
    """Generate summary and send via MCP socket."""
    try:
        log("=== Summarizer started ===")
        log(f"Args: {sys.argv}")

        if len(sys.argv) != 4:
            log(f"Invalid args count: {len(sys.argv)}")
            sys.exit(1)

        teleclaude_session_id = sys.argv[1]
        session_id = sys.argv[2]
        transcript_path = sys.argv[3]

        log(f"Session ID: {session_id}")
        log(f"TeleClaude Session ID: {teleclaude_session_id}")
        log(f"Transcript path: {transcript_path}")

        # Read transcript
        transcript = Path(transcript_path).read_text()
        log(f"Transcript length: {len(transcript)} chars")

        # Generate summary using Claude API
        summary = generate_summary(transcript)
        log(f"Final summary: {summary}")

        mcp_send(
            "teleclaude__send_notification",
            {
                "session_id": teleclaude_session_id,
                "message": summary,
            },
        )

    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")

    log("=== Summarizer finished ===\n")


if __name__ == "__main__":
    main()
