"""Gemini hook adapter."""

from __future__ import annotations

import argparse
import json

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.hooks.payload_io import JsonObject, read_stdin_payload


class GeminiAdapter:
    """Hook adapter for Gemini CLI."""

    agent_name: str = "gemini"
    mint_events: frozenset[AgentHookEventType] = frozenset({AgentHookEvents.AGENT_SESSION_START})
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonObject]:
        """Read JSON from stdin, event_type from args."""
        event_type: str = args.event_type
        raw_input, raw_data = read_stdin_payload()
        return raw_input, event_type, raw_data

    def normalize_payload(self, data: JsonObject) -> JsonObject:
        """Identity: Gemini already uses canonical field names."""
        return data

    def format_checkpoint_response(self, reason: str) -> str | None:
        return json.dumps({"decision": "deny", "reason": reason})

    def format_memory_injection(self, context: str) -> str:
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "additionalContext": context,
                }
            }
        )
