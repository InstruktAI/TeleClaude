"""Tests for the Codex 0.129+ hook trust state computation.

These tests pin the algorithm against fixtures derived from Codex's Rust source
(``codex-rs/hooks/src/engine/discovery.rs::command_hook_hash`` +
``codex-rs/config/src/fingerprint.rs::version_for_toml``). Reproducing the exact
hash is the only way the installer can pre-trust managed hooks without forcing
the user through the ``/hooks`` TUI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from teleclaude.install.codex_hook_trust import (
    build_codex_managed_hook_state,
    codex_hook_state_key,
    compute_codex_hook_trusted_hash,
)

pytestmark = pytest.mark.unit


def _expected_hash(payload: dict[str, object]) -> str:  # guard: loose-dict - mirrors codex JSON wire shape
    """Reference SHA-256 over the canonical JSON of the normalized identity."""
    canonical = json.dumps(_canonical(payload), separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical(value: object) -> object:
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def test_state_key_format_matches_codex_hook_key_helper() -> None:
    """The persisted state key must equal ``{abs_path}:{event_label}:{group}:{handler}``."""
    key = codex_hook_state_key(
        source_path=Path("/Users/example/.codex/hooks.json"),
        event_label="session_start",
        group_index=0,
        handler_index=0,
    )
    assert key == "/Users/example/.codex/hooks.json:session_start:0:0"


def test_session_start_hash_includes_matcher_and_status_message() -> None:
    """SessionStart preserves the configured matcher and statusMessage."""
    command = '/path/receiver.py --agent codex --cwd "$PWD"'
    expected = _expected_hash(
        {
            "event_name": "session_start",
            "matcher": "startup|resume",
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 600,
                    "async": False,
                    "statusMessage": "Loading session notes",
                }
            ],
        }
    )
    actual = compute_codex_hook_trusted_hash(
        event_label="session_start",
        matcher="startup|resume",
        command=command,
        timeout_sec=None,
        status_message="Loading session notes",
    )
    assert actual == expected


def test_user_prompt_submit_drops_matcher_per_codex_normalization() -> None:
    """UserPromptSubmit always normalizes matcher to None regardless of input."""
    command = '/path/receiver.py --agent codex --cwd "$PWD"'
    expected = _expected_hash(
        {
            "event_name": "user_prompt_submit",
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 600,
                    "async": False,
                }
            ],
        }
    )
    actual = compute_codex_hook_trusted_hash(
        event_label="user_prompt_submit",
        matcher=None,
        command=command,
        timeout_sec=None,
        status_message=None,
    )
    assert actual == expected


def test_stop_hook_uses_explicit_timeout_and_no_matcher() -> None:
    """Stop carries an explicit timeout (30s) and codex strips its matcher."""
    command = '/path/receiver.py --agent codex --cwd "$PWD"'
    expected = _expected_hash(
        {
            "event_name": "stop",
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 30,
                    "async": False,
                }
            ],
        }
    )
    actual = compute_codex_hook_trusted_hash(
        event_label="stop",
        matcher=None,
        command=command,
        timeout_sec=30,
        status_message=None,
    )
    assert actual == expected


def test_managed_hook_state_returns_three_entries_with_distinct_hashes() -> None:
    """The installer-managed payload covers SessionStart, UserPromptSubmit, Stop."""
    hooks_path = Path("/Users/example/.codex/hooks.json")
    receiver_command = '/path/receiver.py --agent codex --cwd "$PWD"'

    state = build_codex_managed_hook_state(
        hooks_path=hooks_path,
        receiver_command=receiver_command,
    )

    expected_keys = {
        f"{hooks_path}:session_start:0:0",
        f"{hooks_path}:user_prompt_submit:0:0",
        f"{hooks_path}:stop:0:0",
    }
    assert set(state) == expected_keys

    hashes = {key: entry["trusted_hash"] for key, entry in state.items()}
    assert all(value.startswith("sha256:") for value in hashes.values())
    assert len(set(hashes.values())) == 3


def test_managed_hook_state_is_deterministic() -> None:
    """Re-running the installer must produce byte-identical hashes (idempotency)."""
    hooks_path = Path("/Users/example/.codex/hooks.json")
    receiver_command = '/path/receiver.py --agent codex --cwd "$PWD"'

    first = build_codex_managed_hook_state(hooks_path=hooks_path, receiver_command=receiver_command)
    second = build_codex_managed_hook_state(hooks_path=hooks_path, receiver_command=receiver_command)

    assert first == second


def test_trusted_hash_changes_when_command_changes() -> None:
    """A different receiver path produces a different hash — that's the trust trigger."""
    base = compute_codex_hook_trusted_hash(
        event_label="session_start",
        matcher="startup|resume",
        command="/old/path --agent codex",
        timeout_sec=None,
        status_message="Loading session notes",
    )
    moved = compute_codex_hook_trusted_hash(
        event_label="session_start",
        matcher="startup|resume",
        command="/new/path --agent codex",
        timeout_sec=None,
        status_message="Loading session notes",
    )
    assert base != moved
