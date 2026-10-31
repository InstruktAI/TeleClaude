"""Codex hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
from types import MappingProxyType

from teleclaude.core.codex_transcript import is_codex_subagent_transcript
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
    ContinueWithReason,
    HookDeliveryMode,
    HookEmission,
    HookPurpose,
    HookResponseFormat,
    HookResponseIntent,
    HookResponseKind,
    NativeHookSpec,
    SubagentDrop,
    SubagentDropReason,
)

# Canonical Codex stdout protocol keys — production and tests share these names
# instead of repeating string literals (Testing — String Assertions, mode #3:
# named-constant identity).
CODEX_OUTPUT_HOOK_SPECIFIC = "hookSpecificOutput"
CODEX_OUTPUT_HOOK_EVENT_NAME = "hookEventName"
CODEX_OUTPUT_ADDITIONAL_CONTEXT = "additionalContext"
_DECISION_FIELD = "decision"
_REASON_FIELD = "reason"
_BLOCK_DECISION = "block"
_UNSUPPORTED_DELIVERY_EVENT = "Codex event does not support control delivery"
_TRANSCRIPT_PATH_FIELD = "transcript_path"
_TOOL_USE_ID_FIELD = "tool_use_id"
_TOOL_CALL_ID_FIELD = "tool_call_id"
_POST_COMPACT_TRIGGER_FIELD = "trigger"
_POST_COMPACT_MANUAL_TRIGGER = "manual"
_POST_COMPACT_AUTO_TRIGGER = "auto"
_INVALID_POST_COMPACT_TRIGGER = "Codex PostCompact payload requires a manual or auto trigger"


class CodexHookEvent(StrEnum):
    """Codex's native hook vocabulary owned by its adapter."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PERMISSION_REQUEST = "PermissionRequest"
    POST_COMPACT = "PostCompact"
    STOP = "Stop"


class CodexAdapter(HookAdapter):
    """Hook adapter for Codex."""

    agent_name: str = "codex"
    native_hook_specs = MappingProxyType(
        {
            CodexHookEvent.SESSION_START: NativeHookSpec(
                AgentHookEvents.AGENT_SESSION_START,
                frozenset({HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            CodexHookEvent.USER_PROMPT_SUBMIT: NativeHookSpec(
                AgentHookEvents.USER_PROMPT_SUBMIT,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            CodexHookEvent.PRE_TOOL_USE: NativeHookSpec(
                AgentHookEvents.PRE_TOOL_USE,
                frozenset(),
            ),
            CodexHookEvent.POST_TOOL_USE: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            CodexHookEvent.PERMISSION_REQUEST: NativeHookSpec(AgentHookEvents.AGENT_BLOCKED, frozenset()),
            CodexHookEvent.POST_COMPACT: NativeHookSpec(
                AgentHookEvents.AGENT_IDLE,
                frozenset(),
            ),
            CodexHookEvent.STOP: NativeHookSpec(
                AgentHookEvents.AGENT_STOP,
                frozenset({HookPurpose.MINT}),
                HookDeliveryMode.CONTINUATION_REASON,
            ),
        }
    )
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin and resolve the raw event from the payload."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Normalize Codex payload aliases to the TeleClaude hook shape."""
        normalized = normalize_common_payload(
            data,
            prompt_keys=("prompt", "user_prompt"),
            message_keys=("message", "last_assistant_message"),
        )
        tool_call_id = normalized.get(_TOOL_USE_ID_FIELD)
        if isinstance(tool_call_id, str) and tool_call_id:
            normalized[_TOOL_CALL_ID_FIELD] = tool_call_id
        return normalized

    def normalize_event(self, raw_event_type: str, data: JsonDict) -> HookEventNormalization:
        """Map only provider-confirmed manual compaction to an idle boundary."""
        if raw_event_type == CodexHookEvent.POST_COMPACT:
            trigger = data.get(_POST_COMPACT_TRIGGER_FIELD)
            if trigger == _POST_COMPACT_MANUAL_TRIGGER:
                return HookEventNormalization(AgentHookEvents.AGENT_IDLE, HookNormalizationReason.MAPPED_EVENT)
            if trigger == _POST_COMPACT_AUTO_TRIGGER:
                return HookEventNormalization(None, HookNormalizationReason.PROVIDER_NOT_IDLE)
            raise ValueError(_INVALID_POST_COMPACT_TRIGGER)
        return super().normalize_event(raw_event_type, data)

    def subagent_disposition(self, raw_event_type: str, data: JsonDict) -> SubagentDrop | None:
        """Discard every hook whose transcript belongs to a spawned Codex subagent."""
        del raw_event_type
        transcript_path = data.get(_TRANSCRIPT_PATH_FIELD)
        if isinstance(transcript_path, str) and is_codex_subagent_transcript(transcript_path):
            return SubagentDrop(SubagentDropReason.CODEX_SUBAGENT)
        return None

    def render_response(self, hook_event_name: str, intent: HookResponseIntent) -> HookEmission:
        """Render context without using fields unavailable on Codex Stop."""
        spec = self.native_hook_specs.get(hook_event_name)
        if spec is None or spec.delivery_mode is None:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        if isinstance(intent, ContinueWithReason):
            payload = json.dumps({_DECISION_FIELD: _BLOCK_DECISION, _REASON_FIELD: intent.reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        if HookPurpose.CONTROL_DELIVERY not in spec.purposes:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        payload = json.dumps(
            {
                CODEX_OUTPUT_HOOK_SPECIFIC: {
                    CODEX_OUTPUT_HOOK_EVENT_NAME: hook_event_name,
                    CODEX_OUTPUT_ADDITIONAL_CONTEXT: intent.context,
                }
            }
        )
        return HookEmission(payload, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.JSON)
