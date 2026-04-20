"""Codex hook adapter."""

from __future__ import annotations

import argparse
import json

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import normalize_common_payload, parse_stdin_hook_input


class CodexAdapter:
    """Hook adapter for Codex."""

    agent_name: str = "codex"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {
            AgentHookEvents.AGENT_SESSION_START,
            AgentHookEvents.AGENT_STOP,
        }
    )
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin and resolve the raw event from the payload."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Normalize Codex payload aliases to the TeleClaude hook shape."""
        return normalize_common_payload(
            data,
            prompt_keys=("prompt", "user_prompt"),
            message_keys=("message", "last_assistant_message"),
        )

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize Codex Stop continuation JSON."""
        return json.dumps({"decision": "block", "reason": reason})

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Codex additional-context output is currently unused."""
        del hook_event_name
        del context
        return ""
