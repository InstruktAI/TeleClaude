"""Functional bindings for tmux pane orchestration scenarios."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

import teleclaude.core.tmux_bridge._pane as tmux_pane_mod
import teleclaude.core.tmux_bridge._session as tmux_session_mod
from teleclaude.core.tmux_bridge._subprocess import MAX_CONCURRENT_SNAPSHOTS

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_DRAIN_TURNS = 200
_TMUX_SHELL_COMMAND_SUFFIX = "PATH=/usr/bin exec /tmp/teleclaude-shell"


class _ConcurrencyTrackingTmuxProcess:
    """Fake tmux client whose lifetime is observed from spawn through communicate().

    The counter passed in is incremented by the patched create_subprocess_exec at
    the moment this fake is constructed (spawn) and decremented only when
    communicate() returns, so the live count reflects processes that are actually
    holding a tmux client open, not merely requesters that have started.
    """

    def __init__(
        self, session_name: str, release_event: asyncio.Event, on_communicate_done: Callable[[], None]
    ) -> None:
        self.pid = 4444
        self.returncode = 0
        self._session_name = session_name
        self._release_event = release_event
        self._on_communicate_done = on_communicate_done

    async def communicate(self, input_data: bytes | None = None) -> tuple[bytes, bytes]:
        del input_data
        await self._release_event.wait()
        self._on_communicate_done()
        stdout = f"output-for-{self._session_name}\n{tmux_pane_mod._SNAPSHOT_MARKER}\n0\n".encode()
        return stdout, b""


@pytest.mark.spec("project/spec/feature/agent_runtime/tmux-pane-orchestration", "UC-TPO1")
async def test_concurrent_snapshots_are_bounded_against_the_multiplexer_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requester_count = MAX_CONCURRENT_SNAPSHOTS * 2 + 2
    live = 0
    peak = 0
    release_event = asyncio.Event()

    def _on_communicate_done() -> None:
        nonlocal live
        live -= 1

    async def fake_create_subprocess_exec(*cmd: object, **kwargs: object) -> _ConcurrencyTrackingTmuxProcess:
        del kwargs
        nonlocal live, peak
        session_name = str(cmd[3])
        live += 1
        peak = max(peak, live)
        return _ConcurrencyTrackingTmuxProcess(session_name, release_event, _on_communicate_done)

    monkeypatch.setattr(tmux_pane_mod.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    session_names = [f"snapshot-session-{i}" for i in range(requester_count)]
    tasks = [asyncio.ensure_future(tmux_pane_mod.collect_pane_snapshot(name)) for name in session_names]

    # Drain every synchronously-resolvable step: a requester that acquires a slot
    # spawns and then blocks in communicate() on release_event; a requester beyond
    # the bound blocks on the semaphore itself before ever spawning. Neither path
    # depends on real time, so a fixed number of scheduling turns settles the
    # system deterministically without any wall-clock wait.
    for _ in range(_DRAIN_TURNS):
        await asyncio.sleep(0)

    # A requester beyond the bound must still be waiting for a slot, never having
    # spawned its own multiplexer process — this is what UC-TPO1 requires and what
    # distinguishes "acquire the slot before spawning" from "acquire it only
    # around communicate()", which would let every requester spawn immediately.
    assert live == MAX_CONCURRENT_SNAPSHOTS
    assert peak == MAX_CONCURRENT_SNAPSHOTS

    release_event.set()
    results = await asyncio.gather(*tasks)

    assert peak == MAX_CONCURRENT_SNAPSHOTS
    assert live == 0
    for session_name, snapshot in zip(session_names, results, strict=True):
        assert snapshot.session_exists is True
        assert snapshot.output_raw.strip() == f"output-for-{session_name}"


@pytest.mark.spec("project/spec/feature/agent_runtime/tmux-pane-orchestration", "UC-TPO3")
async def test_pane_command_enters_requested_directory_before_restoring_environment(tmp_path: Path) -> None:
    working_dir = tmp_path / "project with spaces"
    env_file = tmp_path / "agent-env.sh"

    command = tmux_session_mod._build_tmux_shell_command(
        {"PATH": "/usr/bin"},
        Path("/tmp/teleclaude-shell"),
        working_dir=str(working_dir),
        source_env_file=env_file,
    )

    assert command.startswith(f"cd '{working_dir}' || exit 72 ; . {env_file} ;")
    assert command.endswith(_TMUX_SHELL_COMMAND_SUFFIX)


class _CompletedTmuxProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    async def communicate(self, input_data: bytes | None = None) -> tuple[bytes, bytes]:
        del input_data
        return self.stdout, self.stderr


@pytest.mark.spec("project/spec/feature/agent_runtime/tmux-pane-orchestration", "UC-TPO3")
async def test_pane_with_wrong_working_directory_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = tmp_path / "requested"
    inherited = tmp_path / "deleted-worktree"
    killed: list[str] = []

    async def fake_create_subprocess_exec(*cmd: object, **kwargs: object) -> _CompletedTmuxProcess:
        del cmd, kwargs
        return _CompletedTmuxProcess(f"{inherited}\n".encode())

    async def fake_kill_session(name: str) -> bool:
        killed.append(name)
        return True

    monkeypatch.setattr(tmux_session_mod.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(tmux_session_mod, "kill_session", fake_kill_session)

    valid = await tmux_session_mod._validate_tmux_pane_working_directory("agent-1", str(requested))

    assert valid is False
    assert killed == ["agent-1"]
