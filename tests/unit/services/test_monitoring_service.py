"""Characterization tests for teleclaude.services.monitoring_service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from teleclaude.services.monitoring_service import MonitoringService, _get_fd_count, _get_rss_kb


class _FakeAPIServer:
    def __init__(self, clients: set[object]) -> None:
        self._ws_clients = clients


def _make_service(tmp_path: Path) -> MonitoringService:
    return MonitoringService(
        lifecycle=SimpleNamespace(api_server=None),
        task_registry=SimpleNamespace(task_count=lambda: 4),
        shutdown_event=asyncio.Event(),
        start_time=100.0,
        resource_snapshot_interval_s=1.0,
        launchd_watch_interval_s=1.0,
        db_path=str(tmp_path / "teleclaude.sqlite"),
    )


class TestFdAndRssHelpers:
    @pytest.mark.unit
    def test_get_fd_count_returns_none_on_oserror(self) -> None:
        with patch("teleclaude.services.monitoring_service.os.listdir", side_effect=OSError("unavailable")):
            assert _get_fd_count() is None

    @pytest.mark.unit
    def test_get_rss_kb_normalizes_darwin_units(self) -> None:
        usage = SimpleNamespace(ru_maxrss=8 * 1024 * 1024)
        with (
            patch("teleclaude.services.monitoring_service.resource.getrusage", return_value=usage),
            patch("teleclaude.services.monitoring_service.platform.system", return_value="Darwin"),
        ):
            assert _get_rss_kb() == 8192


class TestMonitoringService:
    @pytest.mark.unit
    def test_collect_resource_snapshot_tracks_hwm_and_ws_clients(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        service._lifecycle.api_server = _FakeAPIServer({object(), object()})
        service._last_loop_lag_ms = 12.5
        wal_path = tmp_path / "teleclaude.sqlite-wal"
        wal_path.write_bytes(b"x" * 2048)

        with (
            patch("teleclaude.services.monitoring_service.APIServer", _FakeAPIServer),
            patch("teleclaude.services.monitoring_service.asyncio.all_tasks", return_value={1, 2, 3}),
            patch("teleclaude.services.monitoring_service.time.time", return_value=145.0),
        ):
            snapshot = service._collect_resource_snapshot("manual")

        assert snapshot["reason"] == "manual"
        assert snapshot["uptime_s"] == 45
        assert snapshot["tracked_tasks"] == 4
        assert snapshot["tracked_tasks_hwm"] == 4
        assert snapshot["wal_size_kb"] == 2
        assert snapshot["api_ws_clients"] == 2
        assert snapshot["loop_lag_ms"] == 12.5

    @pytest.mark.unit
    def test_check_pressure_warns_for_fd_tasks_and_lag(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        snapshot = {
            "fd_count": 500,
            "asyncio_tasks": 900,
            "loop_lag_ms": 2000.0,
        }

        with patch("teleclaude.services.monitoring_service.logger.warning") as warn_mock:
            service._check_pressure(snapshot)

        assert warn_mock.call_count == 3

    @pytest.mark.unit
    async def test_launchd_watch_loop_returns_immediately_off_macos(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        with patch("teleclaude.services.monitoring_service.platform.system", return_value="Linux"):
            await service.launchd_watch_loop()
