"""Unit tests for per-session TMPDIR handling in terminal_bridge."""

from __future__ import annotations

import os
import shutil
import socket
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_tmux_session_injects_per_session_tmpdir(tmp_path, monkeypatch):
    """Ensure create_tmux_session injects TMPDIR/TMP/TEMP pointing at a per-session empty dir."""
    from teleclaude.core import terminal_bridge

    base = tmp_path / "teleclaude_tmp"
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(base))

    proc = MagicMock()
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=None)

    original_env = {"FOO": "bar"}
    with patch.object(terminal_bridge.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
        ok = await terminal_bridge.create_tmux_session(
            name="tc_test",
            working_dir=str(tmp_path),
            cols=80,
            rows=24,
            session_id="abc123",
            env_vars=original_env,
        )

    assert ok is True
    # Ensure we don't mutate caller env_vars
    assert original_env == {"FOO": "bar"}

    expected_tmpdir = base / "abc123"
    assert expected_tmpdir.exists()
    assert expected_tmpdir.is_dir()

    called_args = mock_exec.call_args[0]
    assert called_args[0] == "tmux"
    assert "-e" in called_args
    assert f"TMPDIR={expected_tmpdir}" in called_args
    assert f"TMP={expected_tmpdir}" in called_args
    assert f"TEMP={expected_tmpdir}" in called_args


@pytest.mark.asyncio
async def test_create_tmux_session_cleans_existing_tmpdir_with_socket(tmp_path, monkeypatch):
    """Ensure any pre-existing unix sockets in the per-session TMPDIR are removed before tmux starts."""
    from teleclaude.core import terminal_bridge

    # AF_UNIX socket paths have a fairly small length limit (notably on macOS).
    # Use a short base path under /tmp to keep the socket path safely below the limit.
    base = Path("/tmp") / f"tc_tmp_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    try:
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(base))

        session_tmp = base / "abc123"
        session_tmp.mkdir(parents=True, exist_ok=True)
        sock_path = session_tmp / "docker_cli_deadbeef"

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(sock_path))
        finally:
            sock.close()

        assert sock_path.exists()

        proc = MagicMock()
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=None)

        with patch.object(terminal_bridge.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            ok = await terminal_bridge.create_tmux_session(
                name="tc_test",
                working_dir=str(tmp_path),
                session_id="abc123",
            )

        assert ok is True
        assert session_tmp.exists()
        assert not sock_path.exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)
