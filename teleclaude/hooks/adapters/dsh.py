"""DeepSeek Harness hook adapter.

The dsh-hooks plugin fork emits Claude Code style hook events with CC-shaped
payloads (session_id, transcript_path, cwd, permission_mode, hook_event_name,
plus event-specific fields). This adapter therefore shares the Claude/Codex
stdin-JSON parsing path and needs only the canonical aliases — the payload
already carries ``prompt`` and ``last_assistant_message`` under CC names.

Responses ride the same CC stdout-JSON channels the plugin consumes:

- checkpoint block  -> {"decision": "block", "reason": ...}  (Stop continuation)
- additional context -> {"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}
"""

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

# Canonical CC stdout-protocol keys the dsh-hooks plugin parses back.
DSH_OUTPUT_HOOK_SPECIFIC = "hookSpecificOutput"
DSH_OUTPUT_HOOK_EVENT_NAME = "hookEventName"
DSH_OUTPUT_ADDITIONAL_CONTEXT = "additionalContext"
_DECISION_FIELD = "decision"
_REASON_FIELD = "reason"
_BLOCK_DECISION = "block"
_UNSUPPORTED_DELIVERY_EVENT = "DeepSeek event does not support control delivery"


class DshHookEvent(StrEnum):
    """DeepSeek Harness's native hook vocabulary owned by its adapter."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"
    STOP_FAILURE = "StopFailure"


class DshAdapter(HookAdapter):
    """Hook adapter for DeepSeek Harness (dsh-hooks plugin fork)."""

    agent_name: str = "deepseek"
    native_hook_specs = MappingProxyType(
        {
            DshHookEvent.SESSION_START: NativeHookSpec(
                AgentHookEvents.AGENT_SESSION_START,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            DshHookEvent.USER_PROMPT_SUBMIT: NativeHookSpec(
                AgentHookEvents.USER_PROMPT_SUBMIT,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            DshHookEvent.PRE_TOOL_USE: NativeHookSpec(
                AgentHookEvents.PRE_TOOL_USE,
                frozenset({HookPurpose.ACTIVITY}),
            ),
            DshHookEvent.POST_TOOL_USE: NativeHookSpec(
                AgentHookEvents.POST_TOOL_USE,
                frozenset({HookPurpose.CONTROL_DELIVERY}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            DshHookEvent.STOP: NativeHookSpec(
                AgentHookEvents.AGENT_STOP,
                frozenset({HookPurpose.ACTIVITY, HookPurpose.CONTROL_DELIVERY, HookPurpose.MINT}),
                HookDeliveryMode.HOOK_SPECIFIC_CONTEXT,
            ),
            DshHookEvent.STOP_FAILURE: NativeHookSpec(
                AgentHookEvents.AGENT_ERROR,
                frozenset({HookPurpose.ACTIVITY}),
            ),
        }
    )
    supports_hook_checkpoint: bool = True

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Read the CC-shaped JSON payload from stdin; event name from args or payload."""
        return parse_stdin_hook_input(args)

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Normalize CC aliases (last_assistant_message) to TeleClaude names."""
        return normalize_common_payload(
            data,
            prompt_keys=("prompt", "user_prompt"),
            message_keys=("message", "last_assistant_message"),
        )

    def render_response(self, hook_event_name: str, intent: HookResponseIntent) -> HookEmission:
        """Render the documented Claude-compatible DeepSeek stdout subset."""
        spec = self.native_hook_specs.get(hook_event_name)
        if spec is None or spec.delivery_mode is None:
            raise ValueError(_UNSUPPORTED_DELIVERY_EVENT)
        if isinstance(intent, ContinueWithReason):
            payload = json.dumps({_DECISION_FIELD: _BLOCK_DECISION, _REASON_FIELD: intent.reason})
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        hook_specific = {
            DSH_OUTPUT_HOOK_EVENT_NAME: hook_event_name,
            DSH_OUTPUT_ADDITIONAL_CONTEXT: intent.context,
        }
        if isinstance(intent, ContinueWithContext):
            payload = json.dumps(
                {
                    _DECISION_FIELD: _BLOCK_DECISION,
                    _REASON_FIELD: intent.reason,
                    DSH_OUTPUT_HOOK_SPECIFIC: hook_specific,
                }
            )
            return HookEmission(payload, HookResponseKind.CHECKPOINT_BLOCK, HookResponseFormat.JSON)
        payload = json.dumps({DSH_OUTPUT_HOOK_SPECIFIC: hook_specific})
        return HookEmission(payload, HookResponseKind.STARTUP_CONTEXT, HookResponseFormat.JSON)
