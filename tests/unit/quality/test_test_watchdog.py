"""Unit tests for the master-process watchdog poller and inflight tracker.

Source companion: ``teleclaude/quality/test_watchdog.py``.
"""

from __future__ import annotations

import signal
from pathlib import Path

import pytest

from teleclaude.quality import test_watchdog


@pytest.mark.unit
class TestTierForNodeid:
    def test_unit_path_returns_unit(self) -> None:
        assert test_watchdog.tier_for_nodeid("tests/unit/foo.py::test_bar") == test_watchdog.TIER_UNIT

    def test_functional_path_returns_functional(self) -> None:
        assert test_watchdog.tier_for_nodeid("tests/functional/sub/foo.py::test_bar") == test_watchdog.TIER_FUNCTIONAL

    def test_integration_path_returns_integration(self) -> None:
        assert test_watchdog.tier_for_nodeid("tests/integration/foo.py::test_bar") == test_watchdog.TIER_INTEGRATION

    def test_unknown_path_returns_functional_as_default(self) -> None:
        assert test_watchdog.tier_for_nodeid("misc/strangelocation.py::test_x") == test_watchdog.TIER_FUNCTIONAL

    def test_leading_dot_slash_is_stripped(self) -> None:
        assert test_watchdog.tier_for_nodeid("./tests/unit/foo.py::test_bar") == test_watchdog.TIER_UNIT


@pytest.mark.unit
class TestInflightRecord:
    def test_budget_matches_tier(self) -> None:
        rec = test_watchdog.InflightRecord(worker_pid=1, nodeid="tests/unit/foo.py::test_x", started_monotonic=0.0)
        assert rec.tier == test_watchdog.TIER_UNIT
        assert rec.budget_s == 1.0
        assert rec.kill_threshold_s == 2.0

    def test_functional_record_threshold(self) -> None:
        rec = test_watchdog.InflightRecord(
            worker_pid=1, nodeid="tests/functional/foo.py::test_x", started_monotonic=0.0
        )
        assert rec.budget_s == 5.0
        assert rec.kill_threshold_s == 10.0


@pytest.mark.unit
class TestWriteAndReadInflight:
    _SAMPLE_NODEID = "tests/unit/foo.py::test_bar"

    def test_round_trip_via_real_tmpfs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        test_watchdog.write_inflight(self._SAMPLE_NODEID, 123.45, worker_pid=9999)
        records = test_watchdog.read_all_inflight()
        assert len(records) == 1
        rec = records[0]
        assert rec.worker_pid == 9999
        assert rec.nodeid == self._SAMPLE_NODEID
        assert rec.started_monotonic == 123.45

    def test_clear_removes_record(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        test_watchdog.write_inflight(self._SAMPLE_NODEID, 1.0, worker_pid=7777)
        assert len(test_watchdog.read_all_inflight()) == 1
        test_watchdog.clear_inflight(worker_pid=7777)
        assert test_watchdog.read_all_inflight() == []

    _UNIT_NODEID = "tests/unit/a.py::test_a"
    _FUNCTIONAL_NODEID = "tests/functional/b.py::test_b"

    def test_cleanup_removes_leftovers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        test_watchdog.write_inflight(self._UNIT_NODEID, 1.0, worker_pid=11)
        test_watchdog.write_inflight(self._FUNCTIONAL_NODEID, 2.0, worker_pid=22)
        removed = test_watchdog.cleanup_inflight_files()
        assert removed == 2
        assert test_watchdog.read_all_inflight() == []


@pytest.mark.unit
class TestEvaluate:
    def test_within_budget_does_not_kill(self) -> None:
        rec = test_watchdog.InflightRecord(worker_pid=1, nodeid="tests/unit/foo.py::test_x", started_monotonic=10.0)
        decisions = test_watchdog.evaluate([rec], now_monotonic=10.5)  # 0.5s elapsed, threshold 2s
        assert len(decisions) == 1
        assert decisions[0].should_kill is False
        assert decisions[0].elapsed_s == pytest.approx(0.5)

    def test_exceeded_unit_threshold_kills(self) -> None:
        rec = test_watchdog.InflightRecord(worker_pid=1, nodeid="tests/unit/foo.py::test_x", started_monotonic=0.0)
        decisions = test_watchdog.evaluate([rec], now_monotonic=2.1)  # 2.1s elapsed, threshold 2s
        assert decisions[0].should_kill is True

    def test_exceeded_functional_threshold_kills(self) -> None:
        rec = test_watchdog.InflightRecord(
            worker_pid=1, nodeid="tests/functional/foo.py::test_x", started_monotonic=0.0
        )
        decisions = test_watchdog.evaluate([rec], now_monotonic=10.5)  # 10.5s elapsed, threshold 10s
        assert decisions[0].should_kill is True

    def test_functional_within_threshold_does_not_kill(self) -> None:
        rec = test_watchdog.InflightRecord(
            worker_pid=1, nodeid="tests/functional/foo.py::test_x", started_monotonic=0.0
        )
        decisions = test_watchdog.evaluate([rec], now_monotonic=9.9)
        assert decisions[0].should_kill is False


@pytest.mark.unit
class TestWatchdogPollerTick:
    def test_tick_kills_only_workers_over_threshold(self) -> None:
        records = [
            test_watchdog.InflightRecord(worker_pid=100, nodeid="tests/unit/a.py::t", started_monotonic=0.0),
            test_watchdog.InflightRecord(worker_pid=200, nodeid="tests/unit/b.py::t", started_monotonic=4.0),
        ]
        killed: list[tuple[int, int]] = []
        poller = test_watchdog.WatchdogPoller(
            pytest_proc_poll=lambda: None,
            clock=lambda: 5.0,
            sleep=lambda _s: None,
            read_inflight=lambda: records,
            killer=lambda pid, sig: killed.append((pid, sig)),
        )
        decisions = poller.tick()
        kills = {pid for pid, sig in killed}
        assert kills == {100}, "only pid=100 (elapsed 5s, threshold 2s) should be killed"
        assert all(sig == signal.SIGKILL for _, sig in killed)
        assert any(d.should_kill for d in decisions if d.record.worker_pid == 100)
        assert all(sig == signal.SIGKILL for _, sig in killed)

    def test_tick_does_not_kill_same_worker_twice(self) -> None:
        record = test_watchdog.InflightRecord(worker_pid=100, nodeid="tests/unit/a.py::t", started_monotonic=0.0)
        killed: list[int] = []
        poller = test_watchdog.WatchdogPoller(
            pytest_proc_poll=lambda: None,
            clock=lambda: 5.0,
            sleep=lambda _s: None,
            read_inflight=lambda: [record],
            killer=lambda pid, sig: killed.append(pid),
        )
        poller.tick()
        poller.tick()
        assert killed == [100], "repeated tick must not re-kill the same worker"

    def test_poll_until_exit_returns_process_exit_code(self) -> None:
        # Simulate a process that exits on the second poll.
        polls = iter([None, 0])
        poller = test_watchdog.WatchdogPoller(
            pytest_proc_poll=lambda: next(polls),
            clock=lambda: 0.0,
            sleep=lambda _s: None,
            read_inflight=lambda: [],
            killer=lambda pid, sig: None,
        )
        assert poller.poll_until_exit() == 0
