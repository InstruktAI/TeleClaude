#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
#     "pyyaml",
#     "aiosqlite",
#     "python-telegram-bot",
#     "redis",
# ]
# ///
"""Claude Code stop hook for TeleClaude.

Sends completion messages with AI-generated summaries to TeleClaude sessions when work is complete.
Triggered by Claude Code Stop event (session end).

Usage:
    echo '{"session_id": "abc123", "transcript_path": "..."}' | ./stop.py --notify --summarize

Expected stdin JSON format:
    {
        "session_id": "abc123",
        "stop_hook_active": true,
        "transcript_path": "/path/to/transcript.jsonl"
    }

Exit codes:
    0: Success
    1: Error (logged to stderr)
"""

import argparse
import asyncio
import json
import logging
import os
import random
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Setup minimal logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def get_completion_messages() -> list[str]:
    """Return list of friendly completion messages."""
    return [
        "Work complete!",
        "All done!",
        "Task finished!",
        "Job complete!",
        "Ready for next task!",
    ]


def get_llm_completion_message() -> str:
    """
    Generate completion message using available LLM services.
    Priority order: Anthropic > OpenAI > fallback to random message

    Returns:
        str: Generated or fallback completion message
    """
    # Find LLM helper scripts in reference hooks directory
    claude_hooks_dir = Path.home() / ".claude" / "hooks"
    llm_dir = claude_hooks_dir / "utils" / "llm"

    # Try Anthropic first
    if os.getenv("ANTHROPIC_API_KEY"):
        anth_script = llm_dir / "anth.py"
        if anth_script.exists():
            try:
                result = subprocess.run(
                    ["uv", "run", str(anth_script), "--completion"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    # Try OpenAI second
    if os.getenv("OPENAI_API_KEY"):
        oai_script = llm_dir / "oai.py"
        if oai_script.exists():
            try:
                result = subprocess.run(
                    ["uv", "run", str(oai_script), "--completion"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    # Fallback to random predefined message
    messages = get_completion_messages()
    return random.choice(messages)


def get_last_assistant_message(transcript_path: str):  # type: ignore
    """
    Extract all assistant responses since the last user input from the transcript.

    Args:
        transcript_path: Path to the JSONL transcript file

    Returns:
        str: All assistant text responses since last user input, or None if not found
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    try:
        entries = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

        # Find the last user message
        last_user_idx = -1
        for i in range(len(entries) - 1, -1, -1):
            if entries[i].get("type") == "user":
                last_user_idx = i
                break

        # Collect all assistant text responses after the last user message
        assistant_texts = []
        start_idx = last_user_idx + 1 if last_user_idx >= 0 else 0

        for i in range(start_idx, len(entries)):
            entry = entries[i]
            if entry.get("type") == "assistant":
                message = entry.get("message", {})
                content = message.get("content", [])
                if isinstance(content, list):
                    # Extract only text blocks (skip tool_use blocks)
                    text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
                    if text_parts:
                        assistant_texts.append(" ".join(text_parts))

        return " ".join(assistant_texts) if assistant_texts else None
    except Exception:
        return None


def summarize_response(response_text: str):  # type: ignore
    """
    Summarize a response using available LLM services.

    Args:
        response_text: The text to summarize

    Returns:
        str: A short summary, or None if summarization fails
    """
    if not response_text:
        return None

    # Truncate if too long (keep last 2000 chars to focus on conclusion)
    if len(response_text) > 2000:
        response_text = "..." + response_text[-2000:]

    # Find LLM helper scripts in reference hooks directory
    claude_hooks_dir = Path.home() / ".claude" / "hooks"
    llm_dir = claude_hooks_dir / "utils" / "llm"
    prompt = f"Summarize this AI assistant response in 20 words or less, focusing on what was accomplished:\n\n{response_text}"

    # Try Anthropic first
    if os.getenv("ANTHROPIC_API_KEY"):
        anth_script = llm_dir / "anth.py"
        if anth_script.exists():
            try:
                result = subprocess.run(
                    ["uv", "run", str(anth_script), prompt],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    # Try OpenAI second
    if os.getenv("OPENAI_API_KEY"):
        oai_script = llm_dir / "oai.py"
        if oai_script.exists():
            try:
                result = subprocess.run(
                    ["uv", "run", str(oai_script), prompt],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                pass

    return None


async def bootstrap_teleclaude():  # type: ignore
    """Bootstrap TeleClaude components (config, db, adapter_client).

    Returns:
        Tuple of (config, db, adapter_client)

    Raises:
        RuntimeError: If bootstrap fails
    """
    try:
        # Import TeleClaude modules (after sys.path setup)
        from teleclaude.config import config
        from teleclaude.core.adapter_client import AdapterClient
        from teleclaude.core.db import db

        # Initialize database
        await db.initialize()
        logger.debug("Database initialized")

        # Create AdapterClient and load adapters
        adapter_client = AdapterClient()
        adapter_client._load_adapters()  # pylint: disable=protected-access
        logger.debug("Loaded %d adapter(s)", len(adapter_client.adapters))

        # Wire DB to AdapterClient for UI updates
        db.set_client(adapter_client)

        # Start adapters (required for sending messages)
        await adapter_client.start()
        logger.debug("Adapters started")

        return config, db, adapter_client

    except Exception as e:
        raise RuntimeError(f"Failed to bootstrap TeleClaude: {e}") from e


async def send_completion(session_id: str, transcript_path: str = None, include_summary: bool = True) -> None:
    """Send completion message to TeleClaude session.

    Args:
        session_id: TeleClaude session ID
        transcript_path: Path to transcript file (optional)
        include_summary: Whether to include AI summary (optional)

    Raises:
        RuntimeError: If sending completion fails
    """
    # Bootstrap TeleClaude components
    config, db, adapter_client = await bootstrap_teleclaude()

    try:
        # Verify session exists
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return

        # Try to generate summary if transcript available
        summary = None
        if include_summary and transcript_path:
            last_message = get_last_assistant_message(transcript_path)
            if last_message:
                summary = summarize_response(last_message)
                logger.debug("Generated summary: %s", summary)

        # Get generic completion message
        completion_message = get_llm_completion_message()
        logger.debug("Completion message: %s", completion_message)

        # Construct final message
        if summary:
            final_message = f"{completion_message}\n\nSummary: {summary}"
        else:
            final_message = completion_message

        # Send message via AdapterClient (broadcasts to all UI adapters)
        message_id = await adapter_client.send_message(session_id, final_message)
        logger.debug("Sent completion (message_id=%s)", message_id)

        # Set notification flag in UX state
        await db.set_notification_flag(session_id, True)
        logger.debug("Set notification_sent flag for session %s", session_id[:8])

    except Exception as e:
        raise RuntimeError(f"Failed to send completion: {e}") from e

    finally:
        # Stop adapters gracefully
        for adapter_name, adapter in adapter_client.adapters.items():
            try:
                await adapter.stop()
            except Exception as e:
                logger.warning("Failed to stop %s adapter: %s", adapter_name, e)


async def main_async(args: argparse.Namespace, input_data: dict[str, object]) -> None:
    """Async main logic.

    Args:
        args: Parsed command line arguments
        input_data: JSON input from stdin
    """
    # Extract fields
    session_id = str(input_data.get("session_id", ""))
    transcript_path = str(input_data.get("transcript_path", ""))

    # Log session data (optional - could save to ~/.claude/hooks/logs/)
    # For now, skip session logging to keep it simple

    # Handle --chat flag (convert transcript to JSON array)
    if args.chat and transcript_path and os.path.exists(transcript_path):
        try:
            claude_hooks_dir = Path.home() / ".claude" / "hooks"
            log_dir = claude_hooks_dir / "logs" / session_id
            log_dir.mkdir(parents=True, exist_ok=True)

            chat_data = []
            with open(transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            chat_data.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass  # Skip invalid lines

            # Write to logs/chat.json
            chat_file = log_dir / "chat.json"
            with open(chat_file, "w", encoding="utf-8") as f:
                json.dump(chat_data, f, indent=2)

            logger.debug("Wrote chat.json to %s", chat_file)
        except Exception as e:
            logger.warning("Failed to write chat.json: %s", e)

    # Handle --notify flag (send TeleClaude message)
    if args.notify:
        logger.debug("Sending completion message")
        await send_completion(session_id, transcript_path, include_summary=args.summarize)
    else:
        logger.debug("Skipping completion message (--notify flag not set)")


def main() -> None:
    """Main entry point for stop hook."""
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="TeleClaude stop hook")
        parser.add_argument("--chat", action="store_true", help="Copy transcript to chat.json")
        parser.add_argument("--notify", action="store_true", help="Send completion message to TeleClaude")
        parser.add_argument(
            "--summarize", action="store_true", help="Include AI-generated summary in completion message"
        )
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.load(sys.stdin)

        # Run async logic
        asyncio.run(main_async(args, input_data))

        sys.exit(0)

    except json.JSONDecodeError as e:
        logger.error("Invalid JSON input: %s", e)
        sys.exit(0)  # Exit gracefully

    except Exception as e:
        logger.error("Unexpected error: %s", e)
        sys.exit(0)  # Exit gracefully


if __name__ == "__main__":
    # Load environment variables
    load_dotenv()

    # Add TeleClaude to sys.path (hook runs from project root)
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Run main
    main()
