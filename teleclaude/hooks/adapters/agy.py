"""Antigravity CLI (agy) hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from teleclaude.core.events import AgentHookEvents
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.agy_conversation import read_subagent_origin
from teleclaude.hooks.adapters.base import (
    HookAdapter,
    HookEventNormalization,
    HookNormalizationReason,
    normalize_common_payload,
    parse_stdin_hook_input,
)
from teleclaude.hooks.adapters.contracts import (
    ContinueWithReason,
    HookDeliveryMode,
    HookEmission,
    HookPurpose,
    HookResponseFormat,
    HookResponseIntent,
    HookResponseKind,
    NativeHookSpec,
    SubagentCompletion,
    SubagentDisposition,
    SubagentDrop,
    SubagentDropReason,
)

_INVOCATION_NUM_FIELD = "invocationNum"
_STEP_IDX_FIELD = "stepIdx"
_TOOL_CALL_ID_FIELD = "tool_call_id"
_TOOL_NAME_FIELD = "tool_name"
_TOOL_INPUT_FIELD = "tool_input"
_FULLY_IDLE_FIELD = "fullyIdle"
_ERROR_FIELD = "error"
_DECISION_FIELD = "decision"
_REASON_FIELD = "reason"
_INJECT_STEPS_FIELD = "injectSteps"
_EPHEMERAL_MESSAGE_FIELD = "ephemeralMessage"
_PRE_INVOCATION_EVENT = "PreInvocation"
_PRE_TOOL_USE_EVENT = "PreToolUse"
_POST_TOOL_USE_EVENT = "PostToolUse"
_STOP_EVENT = "Stop"
_INVALID_INVOCATION_NUM = "Antigravity PreInvocation requires a non-negative integer invocationNum"
_INVALID_FULLY_IDLE = "Antigravity Stop requires a boolean fullyIdle"
_UNSUPPORTED_DELIVERY_EVENT = "Antigravity event does not support control delivery"
_CONTINUATION_EVENT_REQUIRED = "Antigravity continuation requires a Stop event"
_CONVERSATION_ID_FIELD = "conversationId"
_SESSION_ID_FIELD = "session_id"
_TRANSCRIPT_PATH_FIELD = "transcript_path"
_NATIVE_TRANSCRIPT_PATH_FIELD = "transcriptPath"


class AgyHookEvent(StrEnum):
    """Antigravity's native hook vocabulary owned by its adapter."""

    PRE_INVOCATION = "PreInvocation"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_INVOCATION = "PostInvocation"
    STOP = "Stop"


class AgyDecision(StrEnum):
    """Provider decision values emitted by Antigravity hooks."""

    ALLOW = "allow"
    CONTINUE = "continue"


class AgyToolCallField(StrEnum):
    """Structured fields used by Antigravity tool-call hooks."""

    ARGS = "args"
    NAME = "name"
    TOOL_CALL = "toolCall"


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


def _hook_transcript_path(data: JsonDict) -> str | None:
    """Return the transcript path a hook carries, in either its native or its normalized field."""
    for field in (_TRANSCRIPT_PATH_FIELD, _NATIVE_TRANSCRIPT_PATH_FIELD):
        value = data.get(field)
        if isinstance(value, str) and value:
            return value
    return None


class AgyAdapter(HookAdapter):
    """Hook adapter for Antigravity CLI (agy)."""

    agent_name: str = "gemini"
    native_hook_specs = MappingProxyType(
        {
            AgyHookEvent.PRE_INVOCATION: NativeHookSpec(
                AgentHookEvents.AGENT_SESSION_START,
                frozenset({HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.INJECT_STEPS,
            ),
            AgyHookEvent.PRE_TOOL_USE: NativeHookSpec(
                AgentHookEvents.PRE_TOOL_USE,
                frozenset(),
            ),
            AgyHookEvent.POST_TOOL_USE: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset(),
            ),
            AgyHookEvent.POST_INVOCATION: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.INJECT_STEPS,
            ),
            AgyHookEvent.STOP: NativeHookSpec(
                AgentHookEvents.AGENT_STOP,
                frozenset({HookPurpose.MINT}),
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
        if _SESSION_ID_FIELD not in normalized:
            conversation_id = normalized.get(_CONVERSATION_ID_FIELD)
            if isinstance(conversation_id, str) and conversation_id:
                normalized[_SESSION_ID_FIELD] = conversation_id
        if _TRANSCRIPT_PATH_FIELD not in normalized:
            transcript_path = normalized.get(_NATIVE_TRANSCRIPT_PATH_FIELD)
            if isinstance(transcript_path, str) and transcript_path:
                normalized[_TRANSCRIPT_PATH_FIELD] = transcript_path
        tool_call = normalized.get(AgyToolCallField.TOOL_CALL)
        if isinstance(tool_call, dict):
            tool_name = tool_call.get(AgyToolCallField.NAME)
            tool_input = tool_call.get(AgyToolCallField.ARGS)
            if isinstance(tool_name, str) and tool_name:
                normalized[_TOOL_NAME_FIELD] = tool_name
            if isinstance(tool_input, dict):
                normalized[_TOOL_INPUT_FIELD] = tool_input
        step_idx = normalized.get(_STEP_IDX_FIELD)
        if isinstance(step_idx, int) and not isinstance(step_idx, bool):
            normalized[_TOOL_CALL_ID_FIELD] = str(step_idx)
        return normalize_common_payload(normalized)

    def classify_execution_kind(self, data: JsonDict) -> str | None:
        """Classify a PreInvocation from the latest typed transcript entry."""
        transcript_path = data.get("transcriptPath")
        if not isinstance(transcript_path, str) or not transcript_path:
            return None
        role = _latest_transcript_role(transcript_path)
        return AgyInvocationKind.PROMPT_ACCEPTED if role == "user" else AgyInvocationKind.MID_TURN

    def subagent_disposition(self, raw_event_type: str, data: JsonDict) -> SubagentDisposition | None:
        """Declare what the receiver does with a hook from a native subagent's execution.

        The subagent is recognized from the origin record in its own conversation store;
        no hook payload field carries that ancestry. A subagent's idle ``Stop`` is its
        root conversation's turn completion, because the parent's last ``Stop`` reports
        the process busy while the subagent still runs and the parent never stops again.
        Every other subagent hook is discarded.
        """
        transcript_path = _hook_transcript_path(data)
        origin = read_subagent_origin(transcript_path) if transcript_path else None
        if origin is None:
            return None
        if raw_event_type == _STOP_EVENT and data.get(_FULLY_IDLE_FIELD) is True:
            payload = dict(data)
            payload.pop(_ERROR_FIELD, None)
            payload[_SESSION_ID_FIELD] = origin.root_conversation_id
            payload[_CONVERSATION_ID_FIELD] = origin.root_conversation_id
            payload[_TRANSCRIPT_PATH_FIELD] = origin.root_transcript_path
            payload[_NATIVE_TRANSCRIPT_PATH_FIELD] = origin.root_transcript_path
            return SubagentCompletion(payload)
        return SubagentDrop(SubagentDropReason.ANTIGRAVITY_SUBAGENT)

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
            error = data.get(_ERROR_FIELD)
            if isinstance(error, str) and error:
                if isinstance(self.subagent_disposition(raw_event_type, data), SubagentCompletion):
                    return HookEventNormalization(AgentHookEvents.AGENT_STOP, HookNormalizationReason.MAPPED_EVENT)
                return HookEventNormalization(AgentHookEvents.AGENT_TURN_FAILED, HookNormalizationReason.MAPPED_EVENT)
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
        if isinstance(intent, ContinueWithReason):
            if spec.delivery_mode is not HookDeliveryMode.CONTINUATION_REASON:
                raise ValueError(_CONTINUATION_EVENT_REQUIRED)
            payload = json.dumps({_DECISION_FIELD: AgyDecision.CONTINUE, _REASON_FIELD: intent.reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_CONTINUE, HookResponseFormat.JSON)
        if HookPurpose.CONTROL_DELIVERY not in spec.purposes:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        payload = json.dumps({_INJECT_STEPS_FIELD: [{_EPHEMERAL_MESSAGE_FIELD: intent.context}]})
        return HookEmission(payload, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.JSON)

    def format_success_response(self, raw_event_type: str) -> str | None:
        """Serialize Antigravity's native success response for each installed hook."""
        if raw_event_type == _PRE_INVOCATION_EVENT:
            return json.dumps({})
        if raw_event_type in {_PRE_TOOL_USE_EVENT, _STOP_EVENT}:
            return json.dumps({_DECISION_FIELD: AgyDecision.ALLOW})
        if raw_event_type == _POST_TOOL_USE_EVENT:
            return json.dumps({})
        return None
