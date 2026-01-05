"""Unit tests for telec CLI helpers."""

from __future__ import annotations

import shlex

from teleclaude.cli import telec as telec_module
from teleclaude.core.ux_state import SessionUXState


def test_wrap_with_script_uses_sh_command(monkeypatch) -> None:
    """Ensure script wrapper uses /bin/sh -c for portability."""
    monkeypatch.setattr(telec_module.shutil, "which", lambda _: "/usr/bin/script")
    cmd = "echo hello && ls"
    log_file = "/tmp/telec.log"

    wrapped = telec_module._wrap_with_script(cmd, log_file)

    expected = f"script -q {shlex.quote(log_file)} /bin/sh -c {shlex.quote(cmd)}"
    assert wrapped == expected


def test_prepare_resume_state_uses_latest_when_no_explicit_session() -> None:
    """When no session ID is provided, prefer agent's latest resume behavior."""
    ux_state = SessionUXState(native_session_id="native-123", thinking_mode="slow")

    prepared = telec_module._prepare_resume_state(ux_state, explicit_session_id=False)

    assert prepared.native_session_id is None
    assert ux_state.native_session_id == "native-123"


def test_prepare_resume_state_keeps_native_when_explicit_session() -> None:
    """When a session ID is provided, keep native_session_id for exact resume."""
    ux_state = SessionUXState(native_session_id="native-456", thinking_mode="slow")

    prepared = telec_module._prepare_resume_state(ux_state, explicit_session_id=True)

    assert prepared.native_session_id == "native-456"
