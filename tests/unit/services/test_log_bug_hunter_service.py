"""Tests for the per-project log bug hunter scheduler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.services.log_bug_hunter_service import LogBugHunterService


def _make_service(
    tmp_path: Path,
    *,
    create_session: AsyncMock | None = None,
    list_active_sessions: AsyncMock | None = None,
    project_slug: str = "demo",
) -> LogBugHunterService:
    async def _create_session(_cmd: object) -> dict[str, str]:
        return {"session_id": "sess-1"}

    async def _list_active_sessions() -> list[object]:
        return []

    return LogBugHunterService(
        create_session=create_session or _create_session,
        list_active_sessions=list_active_sessions or _list_active_sessions,
        project_root=tmp_path,
        project_slug=project_slug,
        state_path=tmp_path / f"{project_slug}.json",
    )


def test_has_candidate_error_signals_detects_traceback() -> None:
    assert LogBugHunterService.has_candidate_error_signals("Traceback (most recent call last):\nValueError: boom")
    assert not LogBugHunterService.has_candidate_error_signals("INFO daemon healthy")


def test_load_state_round_trips_serialized_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "demo.json"
    state_path.write_text(
        json.dumps(
            {
                "last_checked_at": "2026-04-06T08:00:00+00:00",
                "last_dispatched_at": "2026-04-06T08:05:00+00:00",
                "last_status": "dispatched",
                "last_error": None,
                "last_session_id": "sess-123",
            }
        ),
        encoding="utf-8",
    )

    service = _make_service(tmp_path)
    state = service._state

    assert state.last_checked_at == datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    assert state.last_dispatched_at == datetime(2026, 4, 6, 8, 5, tzinfo=UTC)
    assert state.last_status == "dispatched"
    assert state.last_error is None
    assert state.last_session_id == "sess-123"


@pytest.mark.asyncio
async def test_maybe_dispatch_marks_clean_logs_without_dispatch(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    with patch.object(service, "_fetch_recent_logs", AsyncMock(return_value=(True, "INFO daemon healthy\n"))):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is False
    state = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "clean"
    assert state["last_error"] is None


@pytest.mark.asyncio
async def test_maybe_dispatch_records_failure_on_empty_output(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    with patch.object(service, "_fetch_recent_logs", AsyncMock(return_value=(True, ""))):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is False
    state = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "failed"
    assert state["last_error"] == "log query returned no output"


@pytest.mark.asyncio
async def test_maybe_dispatch_spawns_session_when_candidate_errors_present(tmp_path: Path) -> None:
    create_session = AsyncMock(return_value={"session_id": "sess-99"})
    service = _make_service(tmp_path, create_session=create_session)

    with patch.object(
        service,
        "_fetch_recent_logs",
        AsyncMock(return_value=(True, "ERROR daemon blew up\nTraceback (most recent call last):")),
    ):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is True
    create_session.assert_awaited_once()
    state = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "dispatched"
    assert state["last_session_id"] == "sess-99"


@pytest.mark.asyncio
async def test_maybe_dispatch_skips_when_same_project_session_already_active(tmp_path: Path) -> None:
    """An active log_bug_hunter session for **this** project must block dispatch."""

    async def _list_active_sessions() -> list[SimpleNamespace]:
        return [SimpleNamespace(job="log_bug_hunter", project_path=str(tmp_path))]

    create_session = AsyncMock(return_value={"session_id": "sess-should-not-run"})
    service = _make_service(tmp_path, create_session=create_session, list_active_sessions=_list_active_sessions)

    with patch.object(
        service,
        "_fetch_recent_logs",
        AsyncMock(return_value=(True, "ERROR daemon blew up\nTraceback (most recent call last):")),
    ):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is False
    create_session.assert_not_awaited()
    state = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "already-running"


@pytest.mark.asyncio
async def test_maybe_dispatch_allows_dispatch_when_other_project_session_active(tmp_path: Path) -> None:
    """A log_bug_hunter session for a **different** project must not block this one.

    Regression guard for the round-2 review finding: the orchestrator passes the
    same computer-wide session list into every per-project executor, so
    ``_has_active_job_session`` has to scope its check to the executor's own
    ``project_root`` — not just match on ``session.job``. Previously, the first
    project to dispatch would starve every subsequent project in the catalog.
    """
    other_project_root = tmp_path / "other"
    other_project_root.mkdir()
    beta_project_root = tmp_path / "beta"
    beta_project_root.mkdir()

    async def _list_active_sessions() -> list[SimpleNamespace]:
        return [SimpleNamespace(job="log_bug_hunter", project_path=str(other_project_root))]

    create_session = AsyncMock(return_value={"session_id": "sess-beta"})
    service = LogBugHunterService(
        create_session=create_session,
        list_active_sessions=_list_active_sessions,
        project_root=beta_project_root,
        project_slug="beta",
        state_path=beta_project_root / "beta.json",
    )

    with patch.object(
        service,
        "_fetch_recent_logs",
        AsyncMock(return_value=(True, "ERROR daemon blew up\nTraceback (most recent call last):")),
    ):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is True
    create_session.assert_awaited_once()
    state = json.loads((beta_project_root / "beta.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "dispatched"
    assert state["last_session_id"] == "sess-beta"
