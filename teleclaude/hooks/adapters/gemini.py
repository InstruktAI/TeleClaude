"""Gemini hook adapter."""

from __future__ import annotations

import argparse
import json

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import HookAdapter, normalize_common_payload, parse_stdin_hook_input


class GeminiAdapter(HookAdapter):
    """Hook adapter for Gemini CLI."""

    agent_name: str = "gemini"
    mint_events: frozenset[AgentHookEventType] = frozenset({AgentHookEvents.AGENT_SESSION_START})
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin, event_type from args."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Identity: Gemini already uses canonical field names."""
        return normalize_common_payload(data)

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize Gemini's checkpoint block response payload."""
        return json.dumps({"decision": "deny", "reason": reason})

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Serialize Gemini's stdout additional-context payload."""
        del hook_event_name
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "additionalContext": context,
                }
            }
        )
