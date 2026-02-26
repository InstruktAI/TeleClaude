"""Unit tests for per-session TMPDIR handling in tmux_bridge."""

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
    """Ensure _create_tmux_session injects TMPDIR/TMP/TEMP pointing at a per-session empty dir."""
    from teleclaude.core import tmux_bridge

    base = tmp_path / "teleclaude_tmp"
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(base))

    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc_opt = MagicMock()
    proc_opt.returncode = 0
    proc_opt.communicate = AsyncMock(return_value=(b"", b""))
    proc_hook = MagicMock()
    proc_hook.returncode = 0
    proc_hook.communicate = AsyncMock(return_value=(b"", b""))

    original_env = {"FOO": "bar"}
    with patch.object(
        tmux_bridge.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(side_effect=[proc, proc_opt, proc_hook]),
    ) as mock_exec:
        ok = await tmux_bridge._create_tmux_session(
            name="tc_test",
            working_dir=str(tmp_path),
            session_id="abc123",
            env_vars=original_env,
        )

    assert ok is True
    # Ensure we don't mutate caller env_vars
    assert original_env == {"FOO": "bar"}

    expected_tmpdir = base / "abc123"
    assert expected_tmpdir.exists()
    assert expected_tmpdir.is_dir()

    called_args = mock_exec.call_args_list[0][0]
    # Check the first arg is some tmux binary (could be custom launcher or just "tmux")
    assert "tmux" in called_args[0]
    assert "-e" in called_args
    assert f"TMPDIR={expected_tmpdir}" in called_args
    assert f"TMP={expected_tmpdir}" in called_args
    assert f"TEMP={expected_tmpdir}" in called_args


@pytest.mark.asyncio
async def test_create_tmux_session_cleans_existing_tmpdir_with_socket(tmp_path, monkeypatch):
    """Ensure any pre-existing unix sockets in the per-session TMPDIR are removed before tmux starts."""
    from teleclaude.core import tmux_bridge

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
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc_opt = MagicMock()
        proc_opt.returncode = 0
        proc_opt.communicate = AsyncMock(return_value=(b"", b""))
        proc_hook = MagicMock()
        proc_hook.returncode = 0
        proc_hook.communicate = AsyncMock(return_value=(b"", b""))

        with patch.object(
            tmux_bridge.asyncio,
            "create_subprocess_exec",
            new=AsyncMock(side_effect=[proc, proc_opt, proc_hook]),
        ):
            ok = await tmux_bridge._create_tmux_session(
                name="tc_test",
                working_dir=str(tmp_path),
                session_id="abc123",
            )

        assert ok is True
        assert session_tmp.exists()
        assert not sock_path.exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.asyncio
async def test_create_tmux_session_scopes_wrapper_path_to_agent_session(tmp_path, monkeypatch):
    """Ensure TeleClaude wrapper PATH injection is applied only to tmux session env."""
    from teleclaude.core import tmux_bridge

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc_opt = MagicMock()
    proc_opt.returncode = 0
    proc_opt.communicate = AsyncMock(return_value=(b"", b""))
    proc_hook = MagicMock()
    proc_hook.returncode = 0
    proc_hook.communicate = AsyncMock(return_value=(b"", b""))

    with patch.object(
        tmux_bridge.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(side_effect=[proc, proc_opt, proc_hook]),
    ) as mock_exec:
        ok = await tmux_bridge._create_tmux_session(
            name="tc_test",
            working_dir=str(tmp_path),
            session_id="sid",
        )

    assert ok is True
    called_args = mock_exec.call_args_list[0][0]
    path_env = [arg for arg in called_args if isinstance(arg, str) and arg.startswith("PATH=")]
    assert len(path_env) == 1
    assert path_env[0].startswith(f"PATH={tmp_path}/.teleclaude/bin:")


@pytest.mark.asyncio
async def test_create_tmux_session_preserves_existing_wrapper_path_without_dup(tmp_path, monkeypatch):
    """Ensure PATH is still injected when wrapper path already exists."""
    from teleclaude.core import tmux_bridge

    monkeypatch.setenv("HOME", str(tmp_path))
    existing_path = f"{tmp_path}/.teleclaude/bin:/usr/local/bin:/usr/bin"
    monkeypatch.setenv("PATH", existing_path)

    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc_opt = MagicMock()
    proc_opt.returncode = 0
    proc_opt.communicate = AsyncMock(return_value=(b"", b""))
    proc_hook = MagicMock()
    proc_hook.returncode = 0
    proc_hook.communicate = AsyncMock(return_value=(b"", b""))

    with patch.object(
        tmux_bridge.asyncio,
        "create_subprocess_exec",
        new=AsyncMock(side_effect=[proc, proc_opt, proc_hook]),
    ) as mock_exec:
        ok = await tmux_bridge._create_tmux_session(
            name="tc_test",
            working_dir=str(tmp_path),
            session_id="sid",
        )

    assert ok is True
    called_args = mock_exec.call_args_list[0][0]
    path_env = [arg for arg in called_args if isinstance(arg, str) and arg.startswith("PATH=")]
    assert len(path_env) == 1
    assert path_env[0] == f"PATH={existing_path}"
