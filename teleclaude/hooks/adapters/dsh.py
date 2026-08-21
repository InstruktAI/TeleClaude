"""DeepSeek Harness hook adapter.

The dsh-hooks plugin fork emits Claude Code style hook events with CC-shaped
payloads (session_id, transcript_path, cwd, permission_mode, hook_event_name,
plus event-specific fields). This adapter therefore shares the Claude/Codex
stdin-JSON parsing path and needs only the canonical aliases — the payload
already carries ``prompt`` and ``last_assistant_message`` under CC names.

Responses ride the same CC stdout-JSON channels the plugin consumes:

- checkpoint block  -> {"decision": "block", "reason": ...}  (Stop continuation)
- additional context -> {"hookSpecificOutput": {"additionalContext": ...}}
"""

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

# Canonical CC stdout-protocol keys the dsh-hooks plugin parses back.
DSH_OUTPUT_HOOK_SPECIFIC = "hookSpecificOutput"
DSH_OUTPUT_ADDITIONAL_CONTEXT = "additionalContext"


class DshHookEvent(StrEnum):
    """DeepSeek Harness's native hook vocabulary owned by its adapter."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"


class DshAdapter(HookAdapter):
    """Hook adapter for DeepSeek Harness (dsh-hooks plugin fork)."""

    agent_name: str = "deepseek"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {
            AgentHookEvents.AGENT_SESSION_START,
            AgentHookEvents.AGENT_STOP,
        }
    )
    delivery_events: frozenset[StrEnum] = frozenset(
        {
            DshHookEvent.SESSION_START,
            DshHookEvent.USER_PROMPT_SUBMIT,
            DshHookEvent.POST_TOOL_USE,
            DshHookEvent.STOP,
        }
    )
    activity_events: frozenset[StrEnum] = frozenset(
        {
            DshHookEvent.SESSION_START,
            DshHookEvent.USER_PROMPT_SUBMIT,
            DshHookEvent.PRE_TOOL_USE,
            DshHookEvent.STOP,
        }
    )
    supports_hook_checkpoint: bool = True
    checkpoint_response_kind: HookResponseKind = HookResponseKind.CHECKPOINT_BLOCK

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read the CC-shaped JSON payload from stdin; event name from args or payload."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Normalize CC aliases (last_assistant_message) to TeleClaude names."""
        return normalize_common_payload(
            data,
            prompt_keys=("prompt", "user_prompt"),
            message_keys=("message", "last_assistant_message"),
        )

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize the Stop continuation decision the plugin honors."""
        return json.dumps({"decision": "block", "reason": reason})

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Serialize additional context through the CC hookSpecificOutput channel.

        The dsh-hooks plugin reads ``hookSpecificOutput.additionalContext``
        from hook stdout and injects it back into the running turn.
        """
        del hook_event_name
        if not context:
            return ""
        return json.dumps({DSH_OUTPUT_HOOK_SPECIFIC: {DSH_OUTPUT_ADDITIONAL_CONTEXT: context}})

    def format_checkpoint_with_context(self, reason: str, hook_event_name: str, context: str) -> str:
        del hook_event_name
        return json.dumps(
            {
                "decision": "block",
                "reason": reason,
                DSH_OUTPUT_HOOK_SPECIFIC: {DSH_OUTPUT_ADDITIONAL_CONTEXT: context},
            }
        )
