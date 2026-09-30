"""Managed-source admission policy for declared native tool intents."""

from __future__ import annotations

from teleclaude.constants import HookSourceKind
from teleclaude.hooks.adapters.contracts import NativeToolDenial, NativeToolIntent

_NATIVE_SUBAGENT_DENIAL_REASON = "Native Gemini subagent invocations are blocked in TeleClaude-managed sessions."


def native_tool_denial_for_source(
    intent: NativeToolIntent,
    source_kind: HookSourceKind,
) -> NativeToolDenial | None:
    """Deny the declared native subagent intent for every managed hook source."""
    if intent is NativeToolIntent.DENY_NATIVE_SUBAGENT and source_kind is not HookSourceKind.HEADLESS:
        return NativeToolDenial(_NATIVE_SUBAGENT_DENIAL_REASON)
    return None
