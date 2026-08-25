"""Antigravity CLI (agy) hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from teleclaude.core.events import AgentHookEvents
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import (
    HookAdapter,
    HookEventNormalization,
    HookNormalizationReason,
    normalize_common_payload,
    parse_stdin_hook_input,
)
from teleclaude.hooks.adapters.contracts import (
    ContinueWithContext,
    ContinueWithReason,
    HookDeliveryMode,
    HookEmission,
    HookPurpose,
    HookResponseFormat,
    HookResponseIntent,
    HookResponseKind,
    NativeHookSpec,
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
_CONTEXT_SEPARATOR = "\n\n"
_UNSUPPORTED_DELIVERY_EVENT = "Antigravity event does not support control delivery"
_CONTINUATION_EVENT_REQUIRED = "Antigravity continuation requires a Stop event"


class AgyHookEvent(StrEnum):
    """Antigravity's native hook vocabulary owned by its adapter."""

    PRE_INVOCATION = "PreInvocation"
    PRE_TOOL_USE = "PreToolUse"
    POST_INVOCATION = "PostInvocation"
    STOP = "Stop"


class AgyDecision(StrEnum):
    """Provider decision values emitted by Antigravity hooks."""

    ALLOW = "allow"
    CONTINUE = "continue"


class AgyInvocationKind(StrEnum):
    """Structural role of an Antigravity invocation boundary."""

    PROMPT_ACCEPTED = "prompt_accepted"
    MID_TURN = "mid_turn"


def _latest_transcript_role(transcript_path: str) -> str | None:
    """Read the final JSONL record's typed role without interpreting its text."""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        if isinstance(message, dict):
            role = message.get("role")
        else:
            role = entry.get("role")
        if isinstance(role, str):
            return role
    return None


class AgyAdapter(HookAdapter):
    """Hook adapter for Antigravity CLI (agy)."""

    agent_name: str = "gemini"
    native_hook_specs = MappingProxyType(
        {
            AgyHookEvent.PRE_INVOCATION: NativeHookSpec(
                AgentHookEvents.AGENT_SESSION_START,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.INJECT_STEPS,
            ),
            AgyHookEvent.PRE_TOOL_USE: NativeHookSpec(
                AgentHookEvents.PRE_TOOL_USE,
                frozenset({HookPurpose.ACTIVITY}),
            ),
            AgyHookEvent.POST_INVOCATION: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.INJECT_STEPS,
            ),
            AgyHookEvent.STOP: NativeHookSpec(
                AgentHookEvents.AGENT_STOP,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.CONTINUATION_REASON,
            ),
        }
    )
    supports_hook_checkpoint: bool = True

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
        tool_call = normalized.get("toolCall")
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name")
            tool_input = tool_call.get("args")
            if isinstance(tool_name, str) and tool_name:
                normalized["tool_name"] = tool_name
            if isinstance(tool_input, dict):
                normalized["tool_input"] = tool_input
        return normalize_common_payload(normalized)

    def classify_execution_kind(self, data: JsonDict) -> str | None:
        """Classify a PreInvocation from the latest typed transcript entry."""
        transcript_path = data.get("transcriptPath")
        if not isinstance(transcript_path, str) or not transcript_path:
            return None
        role = _latest_transcript_role(transcript_path)
        return AgyInvocationKind.PROMPT_ACCEPTED if role == "user" else AgyInvocationKind.MID_TURN

    def normalize_event(self, raw_event_type: str, data: JsonDict) -> HookEventNormalization:
        """Apply Antigravity lifecycle predicates before shared receiver work."""
        if raw_event_type == _PRE_INVOCATION_EVENT:
            invocation_num = data.get(_INVOCATION_NUM_FIELD)
            if isinstance(invocation_num, bool) or not isinstance(invocation_num, int) or invocation_num < 0:
                raise ValueError(_INVALID_INVOCATION_NUM)
            if invocation_num > 0:
                if self.classify_execution_kind(data) is AgyInvocationKind.PROMPT_ACCEPTED:
                    return HookEventNormalization(
                        AgentHookEvents.USER_PROMPT_SUBMIT, HookNormalizationReason.MAPPED_EVENT
                    )
                return HookEventNormalization(None, HookNormalizationReason.LATER_INVOCATION)
            return HookEventNormalization(AgentHookEvents.AGENT_SESSION_START, HookNormalizationReason.FIRST_INVOCATION)
        if raw_event_type == _STOP_EVENT:
            fully_idle = data.get(_FULLY_IDLE_FIELD)
            if not isinstance(fully_idle, bool):
                raise ValueError(_INVALID_FULLY_IDLE)
            if not fully_idle:
                return HookEventNormalization(None, HookNormalizationReason.PROVIDER_NOT_IDLE)
        return super().normalize_event(raw_event_type, data)

    def render_response(self, hook_event_name: str, intent: HookResponseIntent) -> HookEmission:
        """Render invocation context separately from Stop continuation."""
        spec = self.native_hook_specs.get(hook_event_name)
        if spec is None or spec.delivery_mode is None:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        if isinstance(intent, ContinueWithContext):
            if spec.delivery_mode is not HookDeliveryMode.CONTINUATION_REASON:
                raise ValueError(_CONTINUATION_EVENT_REQUIRED)
            reason = _CONTEXT_SEPARATOR.join((intent.reason, intent.context))
            payload = json.dumps({_DECISION_FIELD: AgyDecision.CONTINUE, _REASON_FIELD: reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_CONTINUE, HookResponseFormat.JSON)
        if isinstance(intent, ContinueWithReason):
            if spec.delivery_mode is not HookDeliveryMode.CONTINUATION_REASON:
                raise ValueError(_CONTINUATION_EVENT_REQUIRED)
            payload = json.dumps({_DECISION_FIELD: AgyDecision.CONTINUE, _REASON_FIELD: intent.reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_CONTINUE, HookResponseFormat.JSON)
        if spec.delivery_mode is HookDeliveryMode.CONTINUATION_REASON:
            payload = json.dumps({_DECISION_FIELD: AgyDecision.CONTINUE, _REASON_FIELD: intent.context})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_CONTINUE, HookResponseFormat.JSON)
        payload = json.dumps({_INJECT_STEPS_FIELD: [{_EPHEMERAL_MESSAGE_FIELD: intent.context}]})
        return HookEmission(payload, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.JSON)

    def format_success_response(self, raw_event_type: str) -> str | None:
        """Serialize Antigravity's native success response for each installed hook."""
        if raw_event_type == _PRE_INVOCATION_EVENT:
            return json.dumps({})
        if raw_event_type in {_PRE_TOOL_USE_EVENT, _STOP_EVENT}:
            return json.dumps({_DECISION_FIELD: AgyDecision.ALLOW})
        return None
