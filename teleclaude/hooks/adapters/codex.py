"""Codex hook adapter."""

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

# Canonical Codex stdout protocol keys — production and tests share these names
# instead of repeating string literals (Testing — String Assertions, mode #3:
# named-constant identity).
CODEX_OUTPUT_HOOK_SPECIFIC = "hookSpecificOutput"
CODEX_OUTPUT_HOOK_EVENT_NAME = "hookEventName"
CODEX_OUTPUT_ADDITIONAL_CONTEXT = "additionalContext"


class CodexAdapter(HookAdapter):
    """Hook adapter for Codex."""

    agent_name: str = "codex"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {
            AgentHookEvents.AGENT_SESSION_START,
            AgentHookEvents.AGENT_STOP,
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
