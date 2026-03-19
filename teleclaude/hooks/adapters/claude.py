"""Claude hook adapter."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, cast

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks import receiver as receiver_module


class ClaudeAdapter:
    """Hook adapter for Claude Code CLI."""

    agent_name: str = "claude"
    mint_events: frozenset[AgentHookEventType] = frozenset({AgentHookEvents.AGENT_SESSION_START})
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin, event_type from args."""
        event_type: str = args.event_type
        receiver = cast(Any, sys.modules.get("teleclaude.hooks.receiver", receiver_module))
        raw_input, raw_data = cast(tuple[str, JsonDict], receiver.read_stdin())
        return raw_input, event_type, raw_data

    def normalize_payload(self, data: JsonDict) -> JsonDict:
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
