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
CODEX_OUTPUT_SYSTEM_MESSAGE = "systemMessage"


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
        """Serialize additional context for Codex via the ``systemMessage`` channel.

        Codex's SessionStart, UserPromptSubmit, and Stop hooks accept a
        ``systemMessage`` field on stdout-JSON (see ``Common output fields``
        in the AGENTS.md hooks doc). Returning it here lets the receiver
        deliver domain baseline content and memory context into the Codex
        agent's startup, matching the contract already used for Claude and
        Gemini. An empty context produces no output so the receiver skips
        printing.
        """
        del hook_event_name
        if not context:
            return ""
        return json.dumps({CODEX_OUTPUT_SYSTEM_MESSAGE: context})
