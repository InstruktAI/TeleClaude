"""Compute Codex 0.129+ hook trust state for installer-managed hooks.

Codex 0.129 introduced a per-hook trust gate (PR openai/codex#20321). Hooks
discovered from ``~/.codex/hooks.json`` count as ``User``-layer (unmanaged) and
are silently dropped from the runnable handler set until ``hooks.state."<key>"``
in ``~/.codex/config.toml`` carries a matching ``trusted_hash``. The TUI's
``/hooks`` flow is the only interactive path, but the persistence target is
plain TOML, so the installer can pre-trust managed hooks deterministically.

The hash algorithm mirrors codex's Rust implementation:

  * ``hook_key`` (``codex-rs/hooks/src/lib.rs``) →
    ``{abs_source_path}:{event_label}:{group_index}:{handler_index}``
  * ``command_hook_hash`` (``codex-rs/hooks/src/engine/discovery.rs``) builds a
    ``NormalizedHookIdentity { event_name, #[serde(flatten)] group }`` after
    forcing matcher to ``None`` for ``UserPromptSubmit``/``Stop`` and
    normalizing ``timeout_sec`` to ``Some(timeout_sec.unwrap_or(600).max(1))``.
  * ``version_for_toml`` (``codex-rs/config/src/fingerprint.rs``) converts the
    TOML value to a JSON value, recursively sorts object keys (canonical JSON),
    serializes compactly, SHA-256 hashes, and returns ``sha256:<hex>``.

TOML drops ``Option::None`` fields during serialization, so ``matcher=None`` and
``status_message=None`` must be omitted from the canonical payload — emitting
``"matcher": null`` would diverge from codex's hash.

The ``(group_index, handler_index)`` for each managed handler must come from
the *final* ``hooks.json`` structure: foreign hooks already in the file shift
TeleClaude blocks to higher indices, and the trust key tracks position rather
than identity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

CODEX_HOOK_DEFAULT_TIMEOUT_SEC: Final[int] = 600
CODEX_HOOK_STOP_TIMEOUT_SEC: Final[int] = 30
CODEX_SESSION_START_MATCHER: Final[str] = "startup|resume"
CODEX_SESSION_START_STATUS_MESSAGE: Final[str] = "Loading session notes"
CODEX_PRE_TOOL_USE_MATCHER: Final[str] = ".*"

CODEX_MANAGED_EVENT_LABELS: Final[frozenset[str]] = frozenset(
    {"session_start", "user_prompt_submit", "pre_tool_use", "stop"}
)


def codex_hook_state_key(
    *,
    source_path: Path,
    event_label: str,
    group_index: int,
    handler_index: int,
) -> str:
    """Build the persisted ``hooks.state.<key>`` identifier for a hook handler."""
    return f"{source_path}:{event_label}:{group_index}:{handler_index}"


def compute_codex_hook_trusted_hash(
    *,
    event_label: str,
    matcher: str | None,
    command: str,
    timeout_sec: int | None,
    status_message: str | None,
) -> str:
    """Return the ``sha256:<hex>`` codex would expose as ``currentHash``."""
    handler: dict[str, object] = {  # guard: loose-dict - codex schema field 'async' shadows the Python keyword
        "type": "command",
        "command": command,
        "timeout": (timeout_sec if timeout_sec is not None else CODEX_HOOK_DEFAULT_TIMEOUT_SEC),
        "async": False,
    }
    if status_message is not None:
        handler["statusMessage"] = status_message

    identity: dict[str, object] = {  # guard: loose-dict - mirrors codex NormalizedHookIdentity wire shape
        "event_name": event_label,
        "hooks": [handler],
    }
    if matcher is not None:
        identity["matcher"] = matcher

    canonical = _canonical_json(identity)
    serialized = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return f"sha256:{digest}"


def build_codex_managed_hook_state(
    *,
    hooks_path: Path,
    receiver_command: str,
    positions: Mapping[str, tuple[int, int]],
) -> dict[str, dict[str, str]]:
    """Build the ``hooks.state`` payload for the TeleClaude-managed Codex hooks.

    ``positions`` maps each managed event label (``session_start``,
    ``user_prompt_submit``, ``stop``) to the ``(group_index, handler_index)``
    where TeleClaude's handler lives in the final ``hooks.json`` after merging
    with any foreign blocks. Hardcoding ``(0, 0)`` would silently mistrust
    managed hooks whenever a foreign block already occupies group zero.

    The shape matches codex's TOML schema: ``{ "<key>": { "trusted_hash": "..." } }``.
    Mirrors the matchers/timeouts written by ``_codex_hook_blocks`` so the hashes
    track any edit to that single source.
    """
    state: dict[str, dict[str, str]] = {}
    for event_label, (group_index, handler_index) in positions.items():
        spec = _MANAGED_HOOK_SPECS.get(event_label)
        if spec is None:
            raise ValueError(
                f"No managed hook spec for label {event_label!r}; add an entry to _MANAGED_HOOK_SPECS "
                f"and CODEX_MANAGED_EVENT_LABELS together with CODEX_TRUST_LABEL_BY_HOOK_NAME."
            )
        key = codex_hook_state_key(
            source_path=hooks_path,
            event_label=event_label,
            group_index=group_index,
            handler_index=handler_index,
        )
        trusted_hash = compute_codex_hook_trusted_hash(
            event_label=event_label,
            matcher=spec.matcher,
            command=receiver_command,
            timeout_sec=spec.timeout_sec,
            status_message=spec.status_message,
        )
        state[key] = {"trusted_hash": trusted_hash}
    return state


def _canonical_json(value: object) -> object:
    if isinstance(value, dict):
        return {key: _canonical_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_json(item) for item in value]
    return value


class _CodexHookSpec:
    """Internal: parameters used to derive the trusted_hash for one managed hook."""

    __slots__ = ("matcher", "status_message", "timeout_sec")

    def __init__(
        self,
        *,
        matcher: str | None,
        timeout_sec: int | None,
        status_message: str | None,
    ) -> None:
        self.matcher = matcher
        self.timeout_sec = timeout_sec
        self.status_message = status_message


_MANAGED_HOOK_SPECS: Final[dict[str, _CodexHookSpec]] = {
    "session_start": _CodexHookSpec(
        matcher=CODEX_SESSION_START_MATCHER,
        timeout_sec=None,
        status_message=CODEX_SESSION_START_STATUS_MESSAGE,
    ),
    "user_prompt_submit": _CodexHookSpec(
        matcher=None,
        timeout_sec=None,
        status_message=None,
    ),
    "pre_tool_use": _CodexHookSpec(
        matcher=CODEX_PRE_TOOL_USE_MATCHER,
        timeout_sec=None,
        status_message=None,
    ),
    "stop": _CodexHookSpec(
        matcher=None,
        timeout_sec=CODEX_HOOK_STOP_TIMEOUT_SEC,
        status_message=None,
    ),
}
