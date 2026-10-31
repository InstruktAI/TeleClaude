"""Shared semantic contracts for native agent hook boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.core.events import AgentHookEventType

_EMPTY_CONTEXT_ERROR = "Hook context must be non-empty"
_EMPTY_REASON_ERROR = "Hook continuation reason must be non-empty"
_EMPTY_TOOL_DENIAL_REASON_ERROR = "Native tool denial reason must be non-empty"
_EMPTY_EMISSION_ERROR = "Hook emission payload must be non-empty"


class HookPurpose(StrEnum):
    """TeleClaude-owned purposes for installing one native hook event."""

    CONTROL_DELIVERY = "control_delivery"
    MINT = "mint"


class HookDeliveryMode(StrEnum):
    """Provider channel used to carry model-facing control context."""

    PLAIN_CONTEXT = "plain_context"
    HOOK_SPECIFIC_CONTEXT = "hook_specific_context"
    CONTINUATION_REASON = "continuation_reason"
    INJECT_STEPS = "inject_steps"


class HookResponseFormat(StrEnum):
    """Serialization formats committed to provider stdout."""

    JSON = "json"
    PLAIN_TEXT = "plain_text"


class HookResponseKind(StrEnum):
    """Closed provider-response categories used by receiver observations."""

    CHECKPOINT_BLOCK = "checkpoint_block"
    CHECKPOINT_CONTINUE = "checkpoint_continue"
    NEUTRAL = "neutral"
    STARTUP_CONTEXT = "startup_context"
    STOP_ALLOW = "stop_allow"
    TOOL_ALLOW = "tool_allow"
    TOOL_DENY = "tool_deny"


class NativeToolIntent(StrEnum):
    """Provider-independent native-tool intents declared by adapters."""

    DENY_NATIVE_SUBAGENT = "deny_native_subagent"


class SubagentDropReason(StrEnum):
    """Closed reasons for discarding a hook that comes from a provider-native subagent."""

    CODEX_SUBAGENT = "codex_subagent"


@dataclass(frozen=True)
class SubagentDrop:
    """The adapter's declaration that a hook comes from a provider-native subagent and is discarded."""

    reason: SubagentDropReason


@dataclass(frozen=True)
class NativeHookSpec:
    """One native event TeleClaude installs and consumes for a provider."""

    normalized_event: AgentHookEventType
    purposes: frozenset[HookPurpose]
    delivery_mode: HookDeliveryMode | None = None


@dataclass(frozen=True)
class DeliverContext:
    """Deliver model-facing context without requesting continuation."""

    context: str

    def __post_init__(self) -> None:
        if not self.context.strip():
            raise ValueError(_EMPTY_CONTEXT_ERROR)


@dataclass(frozen=True)
class ContinueWithReason:
    """Request provider continuation with one non-empty reason."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(_EMPTY_REASON_ERROR)


type HookResponseIntent = DeliverContext | ContinueWithReason


@dataclass(frozen=True)
class NativeToolDenial:
    """One receiver-authorized native tool denial for a provider adapter to render."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(_EMPTY_TOOL_DENIAL_REASON_ERROR)


@dataclass(frozen=True)
class HookEmission:
    """One complete response emitted to a provider hook process."""

    payload: str
    response_kind: HookResponseKind
    response_format: HookResponseFormat

    def __post_init__(self) -> None:
        if not self.payload.strip():
            raise ValueError(_EMPTY_EMISSION_ERROR)
