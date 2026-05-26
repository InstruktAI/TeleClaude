"""Antigravity CLI (agy) hook adapter."""

from __future__ import annotations

import argparse
import json

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import HookAdapter, normalize_common_payload, parse_stdin_hook_input


class AgyAdapter(HookAdapter):
    """Hook adapter for Antigravity CLI (agy)."""

    agent_name: str = "gemini"
    # agy emits no SessionStart hook; the first activity event of a conversation
    # is what mints the session and seeds the synthetic session_start.
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {AgentHookEvents.USER_PROMPT_SUBMIT, AgentHookEvents.TOOL_USE}
    )
    supports_hook_checkpoint: bool = True
    synthesizes_session_start: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin, event_type from args."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Map agy's native field names onto TeleClaude's canonical shape.

        agy emits ``conversationId`` (the brain conversation UUID, which doubles
        as the ``--conversation`` resume id) and ``transcriptPath`` on every
        event, and never carries ``prompt``/``last_assistant_message`` — that
        content is sourced from the transcript by the projection layer.
        """
        normalized = dict(data)
        if "session_id" not in normalized:
            conversation_id = normalized.get("conversationId")
            if isinstance(conversation_id, str) and conversation_id:
                normalized["session_id"] = conversation_id
        if "transcript_path" not in normalized:
            transcript_path = normalized.get("transcriptPath")
            if isinstance(transcript_path, str) and transcript_path:
                normalized["transcript_path"] = transcript_path
        return normalize_common_payload(normalized)

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize agy's checkpoint block response payload."""
        return json.dumps({"decision": "deny", "reason": reason})

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Serialize agy's stdout additional-context payload."""
        del hook_event_name
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "additionalContext": context,
                }
            }
        )
