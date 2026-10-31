"""Hook adapter protocol for agent-specific behavior."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.core.events import AgentHookEventType
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.contracts import (
    HookEmission,
    HookPurpose,
    HookResponseIntent,
    NativeHookSpec,
    SubagentDisposition,
)


def read_stdin_payload() -> tuple[str, dict[str, object]]:  # guard: loose-dict - JSON deserialization
    """Read a JSON object payload from stdin when available."""
    raw_input = ""
    data: dict[str, object] = {}  # guard: loose-dict - JSON deserialization
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read()
        if raw_input.strip():
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object")
            data = cast(dict[str, object], parsed)  # guard: loose-dict - JSON deserialization
    return raw_input, data


def parse_stdin_hook_input(args: argparse.Namespace) -> tuple[str, str, JsonDict]:
    """Read a hook payload from stdin and resolve the raw event name."""
    raw_input, raw_data = read_stdin_payload()
    event_type = args.event_type
    if not isinstance(event_type, str) or not event_type.strip():
        hook_event_name = raw_data.get("hook_event_name")
        if not isinstance(hook_event_name, str) or not hook_event_name.strip():
            raise ValueError("Hook payload is missing hook_event_name")
        event_type = hook_event_name
    return raw_input, event_type, cast(JsonDict, raw_data)


def normalize_common_payload(
    data: JsonDict,
    *,
    prompt_keys: tuple[str, ...] = ("prompt", "user_prompt"),
    message_keys: tuple[str, ...] = ("message", "last_assistant_message"),
) -> JsonDict:
    """Normalize shared hook field aliases to TeleClaude's internal shape."""
    normalized = dict(data)

    if "prompt" not in normalized:
        for key in prompt_keys:
            prompt_value = normalized.pop(key, None)
            if isinstance(prompt_value, str):
                normalized["prompt"] = prompt_value
                break

    if "message" not in normalized:
        for key in message_keys:
            message_value = normalized.pop(key, None)
            if isinstance(message_value, str):
                normalized["message"] = message_value
                break

    return normalized


class HookNormalizationReason(StrEnum):
    """Closed reasons for accepting or deliberately dropping a native hook."""

    MAPPED_EVENT = "mapped_event"
    FIRST_INVOCATION = "first_invocation"
    LATER_INVOCATION = "later_invocation"
    PROVIDER_NOT_IDLE = "provider_not_idle"
    UNHANDLED_EVENT = "unhandled_event"
    NOT_ADMITTED = "not_admitted"
    USAGE_LIMIT_WAIT = "usage_limit_wait"
    SUBAGENT_COMPLETION = "subagent_completion"


@dataclass(frozen=True)
class HookEventNormalization:
    """Provider-owned native-event normalization decision."""

    event_type: str | None
    reason: HookNormalizationReason


class HookAdapter:
    """Protocol for agent-specific hook behavior.

    Each adapter encapsulates the differences between agent CLIs:
    input format, field names, checkpoint responses, and additional context.
    """

    agent_name: str
    native_hook_specs: Mapping[str, NativeHookSpec]
    supports_hook_checkpoint: bool

    @property
    def registered_events(self) -> frozenset[str]:
        """Return every native event TeleClaude installs for this provider."""
        return frozenset(self.native_hook_specs)

    @property
    def mint_events(self) -> frozenset[AgentHookEventType]:
        """Return normalized events allowed to adopt an unknown native session."""
        return frozenset(
            spec.normalized_event for spec in self.native_hook_specs.values() if HookPurpose.MINT in spec.purposes
        )

    @property
    def delivery_events(self) -> frozenset[str]:
        """Return native events that can carry model-facing control context."""
        return frozenset(
            event_name
            for event_name, spec in self.native_hook_specs.items()
            if HookPurpose.CONTROL_DELIVERY in spec.purposes
        )

    def parse_input(self, args: argparse.Namespace) -> tuple[str, str, JsonDict]:
        """Parse agent-specific input into (raw_input, raw_event_type, raw_data).

        Raises ValueError or json.JSONDecodeError on invalid input.
        """
        raise NotImplementedError

    def normalize_payload(self, data: JsonDict) -> JsonDict:
        """Normalize agent-specific field names to canonical internal names.

        After normalization, data uses: session_id, transcript_path, prompt, message.
        """
        raise NotImplementedError

    def normalize_event(self, raw_event_type: str, data: JsonDict) -> HookEventNormalization:
        """Normalize one adapter-declared native event."""
        del data
        spec = self.native_hook_specs.get(raw_event_type)
        if spec is None:
            return HookEventNormalization(None, HookNormalizationReason.UNHANDLED_EVENT)
        return HookEventNormalization(spec.normalized_event, HookNormalizationReason.MAPPED_EVENT)

    def classify_execution_kind(self, data: JsonDict) -> str | None:
        """Return optional provider diagnostic metadata about the execution process."""
        del data
        return None

    def subagent_disposition(self, raw_event_type: str, data: JsonDict) -> SubagentDisposition | None:
        """Declare what the receiver does with a hook from a provider-native subagent.

        ``None`` means the hook belongs to a primary conversation. The receiver applies
        the answer before session resolution, so a subagent's identity never reaches it.
        """
        del raw_event_type, data
        return None

    def render_response(self, hook_event_name: str, intent: HookResponseIntent) -> HookEmission:
        """Render one legal provider response for a closed semantic intent."""
        raise NotImplementedError

    def format_success_response(self, raw_event_type: str) -> str | None:
        """Format a provider success response when stdout is required."""
        del raw_event_type
        return None
