"""Tests for the daemon-owned log bug hunter scheduler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.services.log_bug_hunter_service import LogBugHunterService


def _make_service(tmp_path, *, create_session=None, list_active_sessions=None) -> LogBugHunterService:
    async def _create_session(_cmd):
        return {"session_id": "sess-1"}

    async def _list_active_sessions():
        return []

    return LogBugHunterService(
        create_session=create_session or _create_session,
        list_active_sessions=list_active_sessions or _list_active_sessions,
        project_root=tmp_path,
        state_path=tmp_path / "log-bug-hunter-state.json",
    )


def test_has_candidate_error_signals_detects_traceback() -> None:
    assert LogBugHunterService.has_candidate_error_signals("Traceback (most recent call last):\nValueError: boom")
    assert not LogBugHunterService.has_candidate_error_signals("INFO daemon healthy")


@pytest.mark.asyncio
async def test_maybe_dispatch_marks_clean_logs_without_dispatch(tmp_path) -> None:
    service = _make_service(tmp_path)

    with patch.object(service, "_fetch_recent_logs", AsyncMock(return_value=(True, "INFO daemon healthy\n"))):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is False
    state = json.loads((tmp_path / "log-bug-hunter-state.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "clean"
    assert state["last_error"] is None


@pytest.mark.asyncio
async def test_maybe_dispatch_records_failure_on_empty_output(tmp_path) -> None:
    service = _make_service(tmp_path)

    with patch.object(service, "_fetch_recent_logs", AsyncMock(return_value=(True, ""))):
        dispatched = await service.maybe_dispatch(now=datetime(2026, 4, 6, 8, 0, tzinfo=UTC))

    assert dispatched is False
    state = json.loads((tmp_path / "log-bug-hunter-state.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "failed"
    assert state["last_error"] == "log query returned no output"


@pytest.mark.asyncio
async def test_maybe_dispatch_spawns_session_when_candidate_errors_present(tmp_path) -> None:
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
    state = json.loads((tmp_path / "log-bug-hunter-state.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "dispatched"
    assert state["last_session_id"] == "sess-99"


@pytest.mark.asyncio
async def test_maybe_dispatch_skips_when_log_bug_hunter_session_already_active(tmp_path) -> None:
    async def _list_active_sessions():
        return [SimpleNamespace(job="log_bug_hunter")]

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
    state = json.loads((tmp_path / "log-bug-hunter-state.json").read_text(encoding="utf-8"))
    assert state["last_status"] == "already-running"
