"""Functional coverage for the run-session-with-command Codex loader rewrite."""

from __future__ import annotations

from collections.abc import Awaitable
from pathlib import Path

import pytest
from httpx import AsyncClient
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.models import SessionLaunchIntent, SessionLaunchKind
from teleclaude.paths import COMMANDS_DIR

_SPEC = "project/spec/feature/agent_runtime/run-session-with-command"

_PREPARE_COMMAND = "/next-prepare"
_INTEGRATE_COMMAND = "/next-integrate"
_REVIEW_COMMITS_COMMAND = "/next-review-commits"
_BUILD_COMMAND = "/next-build"
_COMMANDS_DIR_SENTINEL = "<COMMANDS_DIR>"


def _install_launch_intent_capture(monkeypatch: pytest.MonkeyPatch) -> list[SessionLaunchIntent | None]:
    """Capture the launch intent handed to bootstrap at the `/sessions/run` boundary.

    The fixture discards the bootstrap coroutine without awaiting it, so a coroutine
    body never runs. Record synchronously instead: replace the bootstrap with a plain
    callable that appends the intent and returns a throwaway coroutine for the queue to
    close.
    """
    captured: list[SessionLaunchIntent | None] = []

    def _capture_bootstrap(session_id: str, launch_intent: SessionLaunchIntent | None = None) -> Awaitable[None]:
        del session_id
        captured.append(launch_intent)

        async def _noop() -> None:
            return None

        return _noop()

    monkeypatch.setattr(get_command_service(), "_bootstrap_session", _capture_bootstrap)
    return captured


def _redact_commands_dir(message: str | None) -> str | None:
    """Replace the machine-specific commands directory so the prompt snapshots portably."""
    if message is None:
        return None
    return message.replace(str(COMMANDS_DIR), _COMMANDS_DIR_SENTINEL)


async def _run(api: AsyncClient, project: Path, *, command: str, args: str, agent: str) -> object:
    return await api.post(
        "/sessions/run",
        json={"command": command, "args": args, "project": str(project), "agent": agent},
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CLR2")
async def test_codex_non_slug_bound_argless_produces_loader_message(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Codex argless lifecycle commands boot the loader, not a 400."""
    captured = _install_launch_intent_capture(monkeypatch)

    rendered: dict[str, str | None] = {}
    for command in (_PREPARE_COMMAND, _INTEGRATE_COMMAND, _REVIEW_COMMITS_COMMAND):
        captured.clear()
        response = await _run(api, tmp_path, command=command, args="", agent="codex")

        assert response.status_code == 200, response.text
        assert len(captured) == 1
        intent = captured[0]
        assert intent is not None
        assert intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        rendered[command] = _redact_commands_dir(intent.message)

    assert rendered == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CLR1")
async def test_codex_slug_bound_argless_is_rejected(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Codex /next-build with empty args still fails the slug-bound guard with HTTP 400."""
    _install_launch_intent_capture(monkeypatch)

    response = await _run(api, tmp_path, command=_BUILD_COMMAND, args="", agent="codex")

    assert response.status_code == 400
    assert response.json() == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CLR3")
async def test_non_codex_agent_leaves_startup_message_unchanged(
    api: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-Codex agent dispatching /next-integrate keeps the raw command as its startup message."""
    captured = _install_launch_intent_capture(monkeypatch)

    response = await _run(api, tmp_path, command=_INTEGRATE_COMMAND, args="", agent="claude")

    assert response.status_code == 200, response.text
    assert len(captured) == 1
    intent = captured[0]
    assert intent is not None
    assert intent.message == _INTEGRATE_COMMAND
