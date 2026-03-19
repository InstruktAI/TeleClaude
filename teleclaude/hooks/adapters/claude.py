"""Claude hook adapter."""

from __future__ import annotations

import argparse
import json

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.hooks.adapters._stdin import read_stdin_payload


class ClaudeAdapter:
    """Hook adapter for Claude Code CLI."""

    agent_name: str = "claude"
    mint_events: frozenset[AgentHookEventType] = frozenset({AgentHookEvents.AGENT_SESSION_START})
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, dict[str, object]]:  # guard: loose-dict
        """Read JSON from stdin, event_type from args."""
        event_type: str = args.event_type
        raw_input, raw_data = read_stdin_payload()
        return raw_input, event_type, raw_data

    def normalize_payload(self, data: dict[str, object]) -> dict[str, object]:  # guard: loose-dict
        """Identity: Claude already uses canonical field names."""
        return data

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize Claude's checkpoint block response payload."""
        return json.dumps({"decision": "block", "reason": reason})

    def format_memory_injection(self, context: str) -> str:
        """Serialize Claude's SessionStart memory injection payload."""
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
