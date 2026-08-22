"""Claude hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import (
    HookAdapter,
    HookResponseKind,
    normalize_common_payload,
    parse_stdin_hook_input,
)


class ClaudeHookEvent(StrEnum):
    """Claude's native hook vocabulary owned by its adapter."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"


class ClaudeAdapter(HookAdapter):
    """Hook adapter for Claude Code CLI."""

    agent_name: str = "claude"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {AgentHookEvents.AGENT_SESSION_START, AgentHookEvents.AGENT_STOP}
    )
    delivery_events: frozenset[StrEnum] = frozenset(
        {
            ClaudeHookEvent.SESSION_START,
            ClaudeHookEvent.USER_PROMPT_SUBMIT,
            ClaudeHookEvent.POST_TOOL_USE,
            ClaudeHookEvent.STOP,
        }
    )
    activity_events: frozenset[StrEnum] = frozenset(
        {
            ClaudeHookEvent.SESSION_START,
            ClaudeHookEvent.USER_PROMPT_SUBMIT,
            ClaudeHookEvent.PRE_TOOL_USE,
            ClaudeHookEvent.STOP,
        }
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

    def format_event_response(self, reason: str | None, hook_event_name: str, context: str) -> str:
        return json.dumps(
            {
                "decision": "block",
                "reason": reason,
                "hookSpecificOutput": {"hookEventName": hook_event_name, "additionalContext": context},
            }
        )
