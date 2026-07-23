"""Functional regression for session-originated `sessions send` identity headers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from syrupy.assertion import SnapshotAssertion

import teleclaude.core.command_handlers._message as message_mod
import teleclaude.core.inbound_queue as inbound_queue_mod
from teleclaude.constants import ROLE_TASKER, ROLE_WORKER
from teleclaude.core.origins import InputOrigin

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-input-delivery"


def _patch_message_delivery_db(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the db binding on modules the `api` fixture does not already cover.

    `deliver_inbound` and the inbound-queue worker import `db` directly rather
    than through a patched package, so the real send-endpoint-to-delivery chain
    needs its own patch (mirrors `test_remote_activity_delivery.py::_patch_db`).
    """
    monkeypatch.setattr(message_mod, "db", api.db)
    monkeypatch.setattr(inbound_queue_mod, "db", api.db)


async def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 1.0) -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout_s)
    while datetime.now(UTC) < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


async def _create_target_session(api: AsyncClient, tmp_path: Path, *, session_id: str) -> None:
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tc-{session_id}",
        last_input_origin=InputOrigin.TERMINAL.value,
        title="target",
        session_id=session_id,
        project_path=str(tmp_path),
        active_agent="codex",
        emit_session_started=False,
    )


@pytest.mark.spec(_SPEC, "UC-SID1")
@pytest.mark.parametrize("role", [ROLE_WORKER, ROLE_TASKER])
async def test_session_originated_send_is_headered_with_real_role(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: SnapshotAssertion,
    role: str,
    cluster_event_bus: None,
) -> None:
    """A plain send from a session resolving to a machine role is delivered with a real-role header.

    job_runner is intentionally not parametrized here: the CLI clearance table
    for `telec sessions send` (`teleclaude/cli/telec/surface.py`, `_SYS_ALL`)
    does not include job_runner, so a job_runner caller cannot reach this
    endpoint at all today — a pre-existing, unrelated authorization gap. worker
    and tasker exercise the same role-lookup mechanism this fix adds to
    `_machine_origin_marker`, and job_runner shares that mechanism verbatim.
    """
    del cluster_event_bus
    _patch_message_delivery_db(api, monkeypatch)
    target_id = f"target-{role}"
    caller_id = f"caller-{role}"
    await _create_target_session(api, tmp_path, session_id=target_id)
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tc-{caller_id}",
        last_input_origin=InputOrigin.TERMINAL.value,
        title="caller",
        session_id=caller_id,
        system_role=role,
        emit_session_started=False,
    )
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", role)

    captured: list[str] = []

    async def _capture_inject_user_turn(session: object, message_text: str, *, active_agent: str | None) -> bool:
        del session, active_agent
        captured.append(message_text)
        return True

    monkeypatch.setattr(message_mod.tmux_io, "inject_user_turn", _capture_inject_user_turn)
    monkeypatch.setattr(message_mod.tmux_io, "process_text", AsyncMock(return_value=False))

    response = await api.post(
        f"/sessions/{target_id}/message",
        json={"message": "please approve"},
        headers={"x-session-token": token},
    )

    assert response.status_code == 200
    await _wait_until(lambda: bool(captured))
    assert captured[0] == snapshot


@pytest.mark.spec(_SPEC, "UC-SID1")
async def test_session_originated_send_with_unidentifiable_role_is_refused(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    """A session-originated send whose caller role does not resolve is refused, never delivered bare."""
    del cluster_event_bus
    _patch_message_delivery_db(api, monkeypatch)
    target_id = "target-refusal"
    caller_id = "caller-refusal"
    await _create_target_session(api, tmp_path, session_id=target_id)
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tc-{caller_id}",
        last_input_origin=InputOrigin.TERMINAL.value,
        title="caller",
        session_id=caller_id,
        human_role="admin",
        emit_session_started=False,
    )
    token = await api.db.issue_session_token(caller_id, f"human:{caller_id}", "admin")

    inject_user_turn = AsyncMock(return_value=True)
    monkeypatch.setattr(message_mod.tmux_io, "inject_user_turn", inject_user_turn)
    monkeypatch.setattr(message_mod.tmux_io, "process_text", AsyncMock(return_value=False))

    response = await api.post(
        f"/sessions/{target_id}/message",
        json={"message": "approved, proceed"},
        headers={"x-session-token": token},
    )

    assert response.status_code == 409
    inject_user_turn.assert_not_awaited()
