"""Codex hook adapter."""

from __future__ import annotations

import argparse
import json
from typing import cast

from teleclaude.core.events import AgentHookEvents, AgentHookEventType


class CodexAdapter:
    """Hook adapter for Codex CLI.

    Codex notify passes JSON as a positional CLI argument (not stdin).
    Field names use kebab-case and need normalization to canonical internal names.
    """

    agent_name: str = "codex"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {
            AgentHookEvents.AGENT_SESSION_START,
            AgentHookEvents.AGENT_STOP,
        }
    )
    supports_hook_checkpoint: bool = False

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, dict[str, object]]:  # guard: loose-dict
        """Parse JSON from positional arg; event is always agent_stop."""
        raw_input = args.event_type or ""
        if raw_input.strip():
            parsed = json.loads(raw_input)
        else:
            parsed = {}
        if not isinstance(parsed, dict):
            raise ValueError("Codex hook payload must be a JSON object")
        raw_data = cast(dict[str, object], parsed)  # guard: loose-dict
        event_type = "agent_stop"
        return raw_input, event_type, raw_data

    def normalize_payload(self, data: dict[str, object]) -> dict[str, object]:  # guard: loose-dict
        """Map Codex kebab-case fields to canonical internal names."""
        result = dict(data)

        # thread-id -> session_id
        thread_id = result.pop("thread-id", None)
        if thread_id is not None:
            result["session_id"] = thread_id

        # input-messages -> prompt (last element)
        input_messages = result.pop("input-messages", None)
        if isinstance(input_messages, list) and input_messages:
            result["prompt"] = str(input_messages[-1])
        elif isinstance(input_messages, str):
            result["prompt"] = input_messages

        # last-assistant-message -> message
        last_msg = result.pop("last-assistant-message", None)
        if last_msg is not None:
            result["message"] = str(last_msg)

        return result

    def format_checkpoint_response(self, reason: str) -> str | None:
        return None

    def format_memory_injection(self, context: str) -> str:
        return ""
