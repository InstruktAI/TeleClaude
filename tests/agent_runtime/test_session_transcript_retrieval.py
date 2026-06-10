"""Functional tests for session transcript retrieval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TypedDict

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-transcript-retrieval"


class _MessagesStatus(TypedDict):
    agent_status: str | None
    last_agent_stop_at: str | None
    message_count: int


async def _create_session(api: AsyncClient) -> str:
    response = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "transcript-status-test",
            "launch_kind": "empty",
        },
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    assert isinstance(session_id, str)
    return session_id


async def _session_messages_status(
    api: AsyncClient,
    *,
    lifecycle_status: str,
    closed_at: datetime | None,
    last_activity: datetime,
    last_input_at: datetime | None,
    last_agent_stop_at: datetime | None,
) -> _MessagesStatus:
    session_id = await _create_session(api)
    await api.db.update_session(
        session_id,
        lifecycle_status=lifecycle_status,
        closed_at=closed_at,
        last_activity=last_activity,
        last_message_sent_at=last_input_at,
        last_agent_stop_at=last_agent_stop_at,
    )

    response = await api.get(f"/sessions/{session_id}/messages")
    assert response.status_code == 200
    body = response.json()
    return {
        "agent_status": body["agent_status"],
        "last_agent_stop_at": body["last_agent_stop_at"],
        "message_count": len(body["messages"]),
    }


@pytest.mark.spec(_SPEC, "UC-STR1")
async def test_terminal_session_messages_report_idle_agent_status(
    api: AsyncClient,
    cluster_event_bus: None,
    snapshot,
) -> None:
    del cluster_event_bus
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)

    statuses = {
        "closed_status_without_stop": await _session_messages_status(
            api,
            lifecycle_status="closed",
            closed_at=None,
            last_activity=now,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "closing_status_without_stop": await _session_messages_status(
            api,
            lifecycle_status="closing",
            closed_at=None,
            last_activity=now,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "closed_at_marker_without_stop": await _session_messages_status(
            api,
            lifecycle_status="active",
            closed_at=now - timedelta(minutes=1),
            last_activity=now,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "active_without_stop": await _session_messages_status(
            api,
            lifecycle_status="active",
            closed_at=None,
            last_activity=now,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "stopped_without_later_input": await _session_messages_status(
            api,
            lifecycle_status="active",
            closed_at=None,
            last_activity=now,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=now - timedelta(minutes=5),
        ),
        "input_after_stop": await _session_messages_status(
            api,
            lifecycle_status="active",
            closed_at=None,
            last_activity=now,
            last_input_at=now - timedelta(minutes=2),
            last_agent_stop_at=now - timedelta(minutes=5),
        ),
    }

    assert statuses == snapshot
