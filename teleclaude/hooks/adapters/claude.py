"""Claude hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
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

_DECISION_FIELD = "decision"
_REASON_FIELD = "reason"
_BLOCK_DECISION = "block"
_HOOK_SPECIFIC_FIELD = "hookSpecificOutput"
_HOOK_EVENT_NAME_FIELD = "hookEventName"
_ADDITIONAL_CONTEXT_FIELD = "additionalContext"
_UNSUPPORTED_DELIVERY_EVENT = "Claude event does not support control delivery"
_POST_COMPACT_TRIGGER_FIELD = "trigger"
_POST_COMPACT_MANUAL_TRIGGER = "manual"
_POST_COMPACT_AUTO_TRIGGER = "auto"
_INVALID_POST_COMPACT_TRIGGER = "Claude PostCompact payload requires a manual or auto trigger"


class ClaudeHookEvent(StrEnum):
    """Claude's native hook vocabulary owned by its adapter."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_COMPACT = "PostCompact"
    STOP = "Stop"


class ClaudeAdapter(HookAdapter):
    """Hook adapter for Claude Code CLI."""

    agent_name: str = "claude"
    native_hook_specs = MappingProxyType(
        {
            ClaudeHookEvent.SESSION_START: NativeHookSpec(
                AgentHookEvents.AGENT_SESSION_START,
                frozenset({HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.PLAIN_CONTEXT,
            ),
            ClaudeHookEvent.USER_PROMPT_SUBMIT: NativeHookSpec(
                AgentHookEvents.USER_PROMPT_SUBMIT,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.PLAIN_CONTEXT,
            ),
            ClaudeHookEvent.PRE_TOOL_USE: NativeHookSpec(
                AgentHookEvents.PRE_TOOL_USE,
                frozenset(),
            ),
            ClaudeHookEvent.POST_TOOL_USE: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            ClaudeHookEvent.POST_COMPACT: NativeHookSpec(
                AgentHookEvents.AGENT_IDLE,
                frozenset(),
            ),
            ClaudeHookEvent.STOP: NativeHookSpec(
                AgentHookEvents.AGENT_STOP,
                frozenset({HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
        }
    )
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read JSON from stdin, event_type from args."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Identity: Claude already uses canonical field names."""
        return normalize_common_payload(data)

    def normalize_event(self, raw_event_type: str, data: JsonDict) -> HookEventNormalization:
        """Map only provider-confirmed manual compaction to an idle boundary."""
        if raw_event_type == ClaudeHookEvent.POST_COMPACT:
            trigger = data.get(_POST_COMPACT_TRIGGER_FIELD)
            if trigger == _POST_COMPACT_MANUAL_TRIGGER:
                return HookEventNormalization(AgentHookEvents.AGENT_IDLE, HookNormalizationReason.MAPPED_EVENT)
            if trigger == _POST_COMPACT_AUTO_TRIGGER:
                return HookEventNormalization(None, HookNormalizationReason.PROVIDER_NOT_IDLE)
            raise ValueError(_INVALID_POST_COMPACT_TRIGGER)
        return super().normalize_event(raw_event_type, data)

    def render_response(self, hook_event_name: str, intent: HookResponseIntent) -> HookEmission:
        """Render context or continuation through Claude's event-specific channels."""
        spec = self.native_hook_specs.get(hook_event_name)
        if spec is None or spec.delivery_mode is None:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        if isinstance(intent, ContinueWithReason):
            payload = json.dumps({_DECISION_FIELD: _BLOCK_DECISION, _REASON_FIELD: intent.reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        if isinstance(intent, ContinueWithContext):
            payload = json.dumps(
                {
                    _DECISION_FIELD: _BLOCK_DECISION,
                    _REASON_FIELD: intent.reason,
                    _HOOK_SPECIFIC_FIELD: {
                        _HOOK_EVENT_NAME_FIELD: hook_event_name,
                        _ADDITIONAL_CONTEXT_FIELD: intent.context,
                    },
                }
            )
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        if spec.delivery_mode is HookDeliveryMode.PLAIN_CONTEXT:
            return HookEmission(intent.context, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.PLAIN_TEXT)
        payload = json.dumps(
            {
                _HOOK_SPECIFIC_FIELD: {
                    _HOOK_EVENT_NAME_FIELD: hook_event_name,
                    _ADDITIONAL_CONTEXT_FIELD: intent.context,
                }
            }
        )
        return HookEmission(payload, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.JSON)
