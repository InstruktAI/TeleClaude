"""Codex hook adapter."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
from types import MappingProxyType

from teleclaude.core.events import AgentHookEvents
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.base import (
    HookAdapter,
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

# Canonical Codex stdout protocol keys — production and tests share these names
# instead of repeating string literals (Testing — String Assertions, mode #3:
# named-constant identity).
CODEX_OUTPUT_HOOK_SPECIFIC = "hookSpecificOutput"
CODEX_OUTPUT_HOOK_EVENT_NAME = "hookEventName"
CODEX_OUTPUT_ADDITIONAL_CONTEXT = "additionalContext"
_DECISION_FIELD = "decision"
_REASON_FIELD = "reason"
_BLOCK_DECISION = "block"
_CONTEXT_SEPARATOR = "\n\n"
_UNSUPPORTED_DELIVERY_EVENT = "Codex event does not support control delivery"


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
    native_hook_specs = MappingProxyType(
        {
            CodexHookEvent.SESSION_START: NativeHookSpec(
                AgentHookEvents.AGENT_SESSION_START,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            CodexHookEvent.USER_PROMPT_SUBMIT: NativeHookSpec(
                AgentHookEvents.USER_PROMPT_SUBMIT,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            CodexHookEvent.PRE_TOOL_USE: NativeHookSpec(
                AgentHookEvents.PRE_TOOL_USE,
                frozenset({HookPurpose.ACTIVITY}),
            ),
            CodexHookEvent.POST_TOOL_USE: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            CodexHookEvent.STOP: NativeHookSpec(
                AgentHookEvents.AGENT_STOP,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
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
        return normalize_common_payload(
            data,
            prompt_keys=("prompt", "user_prompt"),
            message_keys=("message", "last_assistant_message"),
        )

    def render_response(self, hook_event_name: str, intent: HookResponseIntent) -> HookEmission:
        """Render context without using fields unavailable on Codex Stop."""
        spec = self.native_hook_specs.get(hook_event_name)
        if spec is None or spec.delivery_mode is None:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        if isinstance(intent, ContinueWithContext):
            reason = _CONTEXT_SEPARATOR.join((intent.reason, intent.context))
            payload = json.dumps({_DECISION_FIELD: _BLOCK_DECISION, _REASON_FIELD: reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        if isinstance(intent, ContinueWithReason):
            payload = json.dumps({_DECISION_FIELD: _BLOCK_DECISION, _REASON_FIELD: intent.reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        if spec.delivery_mode is HookDeliveryMode.CONTINUATION_REASON:
            payload = json.dumps({_DECISION_FIELD: _BLOCK_DECISION, _REASON_FIELD: intent.context})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        payload = json.dumps(
            {
                CODEX_OUTPUT_HOOK_SPECIFIC: {
                    CODEX_OUTPUT_HOOK_EVENT_NAME: hook_event_name,
                    CODEX_OUTPUT_ADDITIONAL_CONTEXT: intent.context,
                }
            }
        )
        return HookEmission(payload, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.JSON)
