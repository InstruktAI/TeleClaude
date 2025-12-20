#!/usr/bin/env python3
"""Gemini CLI hook receiver.

Receives events from Gemini CLI, normalizes them, and forwards to TeleClaude.
"""

import json
import os
import sys
from pathlib import Path

# Add parent directory to path to find utils
sys.path.append(str(Path(__file__).parent))

from typing import Any, cast

from instrukt_ai_logging import configure_logging, get_logger
from utils.mcp_send import mcp_send
from utils.normalize import normalize_notification_payload, normalize_session_start_payload

configure_logging("teleclaude")
logger = cast(Any, get_logger("teleclaude.hooks.receiver_gemini"))


def main() -> None:
    try:
        logger.info(
            "receiver start",
            argv=sys.argv,
            cwd=os.getcwd(),
            stdin_tty=sys.stdin.isatty(),
            has_session_id="TELECLAUDE_SESSION_ID" in os.environ,
        )

        # Read input from stdin
        try:
            if not sys.stdin.isatty():
                data = json.load(sys.stdin)
            else:
                data = {}
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from stdin")
            data = {}

        # Get TeleClaude session ID
        teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
        if not teleclaude_session_id:
            logger.info("No TELECLAUDE_SESSION_ID, ignoring")
            sys.exit(0)

        def send_error(message: str, details: dict[str, object] | None = None) -> None:
            mcp_send(
                "teleclaude__handle_agent_event",
                {
                    "session_id": teleclaude_session_id,
                    "event_type": "error",
                    "data": {"message": message, "source": "gemini_hook", "details": details or {}},
                },
            )

        # Get event type from args (passed by setup_gemini_hooks.py)
        event_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"
        event_type = event_type.lower()
        if event_type == "sessionstart":
            event_type = "session_start"

        logger.info(
            "receiver event",
            event_type=event_type,
            session_id=teleclaude_session_id,
        )

        allowed_events = {"session_start", "notification", "stop"}
        if event_type not in allowed_events:
            msg = f"Unknown hook event_type '{event_type}'"
            logger.error(msg, event_type=event_type)
            send_error(msg, {"event_type": event_type})
            sys.exit(1)

        if event_type == "session_start":
            native_session_id, transcript_path = normalize_session_start_payload(data)

            if not native_session_id or not transcript_path:
                msg = "session_start missing required fields: session_id and transcript_path"
                logger.error(
                    msg,
                    data_keys=list(data.keys()),
                    session_id=bool(native_session_id),
                    transcript_path=bool(transcript_path),
                )
                send_error(
                    msg,
                    {
                        "data_keys": list(data.keys()),
                        "session_id_present": bool(native_session_id),
                        "transcript_path_present": bool(transcript_path),
                    },
                )
                sys.exit(1)
        elif event_type == "notification":
            normalize_notification_payload(data)

        # Forward to TeleClaude
        mcp_send(
            "teleclaude__handle_agent_event",
            {"session_id": teleclaude_session_id, "event_type": event_type, "data": data},
        )

    except Exception as e:
        logger.error("Receiver error", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
