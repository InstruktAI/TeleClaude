"""Codex hook adapter."""

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

# Canonical Codex stdout protocol keys — production and tests share these names
# instead of repeating string literals (Testing — String Assertions, mode #3:
# named-constant identity).
CODEX_OUTPUT_HOOK_SPECIFIC = "hookSpecificOutput"
CODEX_OUTPUT_HOOK_EVENT_NAME = "hookEventName"
CODEX_OUTPUT_ADDITIONAL_CONTEXT = "additionalContext"


class CodexHookEvent(StrEnum):
    """Codex's native hook vocabulary owned by its adapter."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"


class CodexAdapter(HookAdapter):
    """Hook adapter for Codex."""

    agent_name: str = "codex"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {
            AgentHookEvents.AGENT_SESSION_START,
            AgentHookEvents.AGENT_STOP,
        }
    )
    delivery_events: frozenset[StrEnum] = frozenset(
        {
            CodexHookEvent.SESSION_START,
            CodexHookEvent.USER_PROMPT_SUBMIT,
            CodexHookEvent.POST_TOOL_USE,
            CodexHookEvent.STOP,
        }
    )
    activity_events: frozenset[StrEnum] = frozenset(
        {
            CodexHookEvent.SESSION_START,
            CodexHookEvent.USER_PROMPT_SUBMIT,
            CodexHookEvent.PRE_TOOL_USE,
            CodexHookEvent.STOP,
        }
    )
    supports_hook_checkpoint: bool = True
    checkpoint_response_kind: HookResponseKind = HookResponseKind.CHECKPOINT_BLOCK

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
        """Serialize additional context for Codex on the model-context channel.

        Codex carries injected content to the model through
        ``hookSpecificOutput.additionalContext``. Its ``systemMessage`` field
        renders in the TUI without reaching the model, so it cannot carry
        context. An empty context produces no output so the receiver skips
        printing.
        """
        if not context:
            return ""
        return json.dumps(
            {
                CODEX_OUTPUT_HOOK_SPECIFIC: {
                    CODEX_OUTPUT_HOOK_EVENT_NAME: hook_event_name,
                    CODEX_OUTPUT_ADDITIONAL_CONTEXT: context,
                }
            }
        )

    def format_checkpoint_with_context(self, reason: str, hook_event_name: str, context: str) -> str:
        response = json.loads(self.format_additional_context(hook_event_name, context))
        response.update({"decision": "block", "reason": reason})
        return json.dumps(response)
