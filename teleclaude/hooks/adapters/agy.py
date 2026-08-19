"""Antigravity CLI (agy) hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum

from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import (
    HookAdapter,
    HookEventNormalization,
    HookNormalizationReason,
    HookResponseKind,
    normalize_common_payload,
    parse_stdin_hook_input,
)

_INVOCATION_NUM_FIELD = "invocationNum"
_FULLY_IDLE_FIELD = "fullyIdle"
_DECISION_FIELD = "decision"
_REASON_FIELD = "reason"
_INJECT_STEPS_FIELD = "injectSteps"
_EPHEMERAL_MESSAGE_FIELD = "ephemeralMessage"
_PRE_INVOCATION_EVENT = "PreInvocation"
_PRE_TOOL_USE_EVENT = "PreToolUse"
_STOP_EVENT = "Stop"
_INVALID_INVOCATION_NUM = "Antigravity PreInvocation requires a non-negative integer invocationNum"
_INVALID_FULLY_IDLE = "Antigravity Stop requires a boolean fullyIdle"


class AgyDecision(StrEnum):
    """Provider decision values emitted by Antigravity hooks."""

    ALLOW = "allow"
    CONTINUE = "continue"


class AgyAdapter(HookAdapter):
    """Hook adapter for Antigravity CLI (agy)."""

    agent_name: str = "gemini"
    mint_events: frozenset[AgentHookEventType] = frozenset(
        {AgentHookEvents.AGENT_SESSION_START, AgentHookEvents.AGENT_STOP}
    )
    supports_hook_checkpoint: bool = True
    checkpoint_response_kind: HookResponseKind = HookResponseKind.CHECKPOINT_CONTINUE

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

    def normalize_event(self, raw_event_type: str, data: JsonDict) -> HookEventNormalization:
        """Apply Antigravity lifecycle predicates before shared receiver work."""
        if raw_event_type == _PRE_INVOCATION_EVENT:
            invocation_num = data.get(_INVOCATION_NUM_FIELD)
            if isinstance(invocation_num, bool) or not isinstance(invocation_num, int) or invocation_num < 0:
                raise ValueError(_INVALID_INVOCATION_NUM)
            if invocation_num > 0:
                return HookEventNormalization(None, HookNormalizationReason.LATER_INVOCATION)
            return HookEventNormalization(AgentHookEvents.AGENT_SESSION_START, HookNormalizationReason.FIRST_INVOCATION)
        if raw_event_type == _STOP_EVENT:
            fully_idle = data.get(_FULLY_IDLE_FIELD)
            if not isinstance(fully_idle, bool):
                raise ValueError(_INVALID_FULLY_IDLE)
            if not fully_idle:
                return HookEventNormalization(None, HookNormalizationReason.PROVIDER_NOT_IDLE)
        return super().normalize_event(raw_event_type, data)

    def format_checkpoint_response(self, reason: str) -> str | None:
        """Serialize Antigravity's execution-loop continuation payload."""
        return json.dumps({_DECISION_FIELD: AgyDecision.CONTINUE, _REASON_FIELD: reason})

    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        """Serialize agy's stdout additional-context payload."""
        del hook_event_name
        return json.dumps({_INJECT_STEPS_FIELD: [{_EPHEMERAL_MESSAGE_FIELD: context}]})

    def format_success_response(self, raw_event_type: str) -> str | None:
        """Serialize Antigravity's native success response for each installed hook."""
        if raw_event_type == _PRE_INVOCATION_EVENT:
            return json.dumps({})
        if raw_event_type in {_PRE_TOOL_USE_EVENT, _STOP_EVENT}:
            return json.dumps({_DECISION_FIELD: AgyDecision.ALLOW})
        return None
