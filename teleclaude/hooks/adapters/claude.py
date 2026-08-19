"""Claude hook adapter."""

from __future__ import annotations

import argparse
import json

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import (
    HookAdapter,
    HookResponseKind,
    normalize_common_payload,
    parse_stdin_hook_input,
)


class ClaudeAdapter(HookAdapter):
    """Hook adapter for Claude Code CLI."""

    agent_name: str = "claude"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {AgentHookEvents.AGENT_SESSION_START, AgentHookEvents.AGENT_STOP}
    )
    supports_hook_checkpoint: bool = True
    checkpoint_response_kind: HookResponseKind = HookResponseKind.CHECKPOINT_BLOCK

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin, event_type from args."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Identity: Claude already uses canonical field names."""
        return normalize_common_payload(data)

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize Claude's checkpoint block response payload."""
        return json.dumps({"decision": "block", "reason": reason})

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Return plain text for Claude Code stdout context injection."""
        del hook_event_name
        return context
