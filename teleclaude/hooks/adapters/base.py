"""Hook adapter protocol for agent-specific behavior."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Protocol, cast

from teleclaude.core.events import AgentHookEventType
from teleclaude.core.models import JsonDict


def read_stdin_payload() -> tuple[str, dict[str, object]]:  # guard: loose-dict - JSON deserialization
    """Read a JSON object payload from stdin when available."""
    raw_input = ""
    data: dict[str, object] = {}  # guard: loose-dict - JSON deserialization
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read()
        if raw_input.strip():
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object")
            data = cast(dict[str, object], parsed)  # guard: loose-dict - JSON deserialization
    return raw_input, data


def parse_stdin_hook_input(args: argparse.Namespace) -> tuple[str, str, JsonDict]:
    """Read a hook payload from stdin and resolve the raw event name."""
    raw_input, raw_data = read_stdin_payload()
    event_type = args.event_type
    if not isinstance(event_type, str) or not event_type.strip():
        hook_event_name = raw_data.get("hook_event_name")
        if not isinstance(hook_event_name, str) or not hook_event_name.strip():
            raise ValueError("Hook payload is missing hook_event_name")
        event_type = hook_event_name
    return raw_input, event_type, cast(JsonDict, raw_data)


def normalize_common_payload(
    data: JsonDict,
    *,
    prompt_keys: tuple[str, ...] = ("prompt", "user_prompt"),
    message_keys: tuple[str, ...] = ("message", "last_assistant_message"),
) -> JsonDict:
    """Normalize shared hook field aliases to TeleClaude's internal shape."""
    normalized = dict(data)

    if "prompt" not in normalized:
        for key in prompt_keys:
            prompt_value = normalized.pop(key, None)
            if isinstance(prompt_value, str):
                normalized["prompt"] = prompt_value
                break

    if "message" not in normalized:
        for key in message_keys:
            message_value = normalized.pop(key, None)
            if isinstance(message_value, str):
                normalized["message"] = message_value
                break

    return normalized


class HookAdapter(Protocol):
    """Protocol for agent-specific hook behavior.

    Each adapter encapsulates the differences between agent CLIs:
    input format, field names, checkpoint responses, and additional context.
    """

    agent_name: str
    mint_events: frozenset[AgentHookEventType]
    supports_hook_checkpoint: bool
    # True when the CLI emits no native session-start hook, so TeleClaude must
    # synthesize a session_start from the first activity event of a conversation.
    synthesizes_session_start: bool

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Parse agent-specific input into (raw_input, raw_event_type, raw_data).

        Raises ValueError or json.JSONDecodeError on invalid input.
        """
        raise NotImplementedError

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Normalize agent-specific field names to canonical internal names.

        After normalization, data uses: session_id, transcript_path, prompt, message.
        """
        raise NotImplementedError

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Format checkpoint blocking response, or None if unsupported."""
        raise NotImplementedError

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Format stdout additional context for a specific hook event."""
        raise NotImplementedError
