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
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

CODEX_HOOK_DEFAULT_TIMEOUT_SEC: Final[int] = 600
CODEX_HOOK_STOP_TIMEOUT_SEC: Final[int] = 30
CODEX_SESSION_START_MATCHER: Final[str] = "startup|resume"
CODEX_SESSION_START_STATUS_MESSAGE: Final[str] = "Loading session notes"


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
) -> dict[str, dict[str, str]]:
    """Build the ``hooks.state`` payload for the three TeleClaude-managed Codex hooks.

    The shape matches codex's TOML schema: ``{ "<key>": { "trusted_hash": "..." } }``.
    Mirrors the matchers/timeouts written by ``_codex_hook_blocks`` so the hashes
    track any edit to that single source.
    """
    hooks: list[_CodexHookSpec] = [
        _CodexHookSpec(
            event_label="session_start",
            matcher=CODEX_SESSION_START_MATCHER,
            timeout_sec=None,
            status_message=CODEX_SESSION_START_STATUS_MESSAGE,
        ),
        _CodexHookSpec(
            event_label="user_prompt_submit",
            matcher=None,
            timeout_sec=None,
            status_message=None,
        ),
        _CodexHookSpec(
            event_label="stop",
            matcher=None,
            timeout_sec=CODEX_HOOK_STOP_TIMEOUT_SEC,
            status_message=None,
        ),
    ]

    state: dict[str, dict[str, str]] = {}
    for spec in hooks:
        key = codex_hook_state_key(
            source_path=hooks_path,
            event_label=spec.event_label,
            group_index=0,
            handler_index=0,
        )
        trusted_hash = compute_codex_hook_trusted_hash(
            event_label=spec.event_label,
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

    __slots__ = ("event_label", "matcher", "status_message", "timeout_sec")

    def __init__(
        self,
        *,
        event_label: str,
        matcher: str | None,
        timeout_sec: int | None,
        status_message: str | None,
    ) -> None:
        self.event_label = event_label
        self.matcher = matcher
        self.timeout_sec = timeout_sec
        self.status_message = status_message
