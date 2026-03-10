"""Unit tests for integrator spawn guard and sessions run in integration_bridge."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.integration_bridge import _spawn_integrator_sync


@pytest.fixture
def _no_environ(monkeypatch):
    """Isolate from real env variables."""
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", "/test/project")


def _make_run_result(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestSpawnGuardUsesJobFilter:
    """Spawn guard uses structured --job filter, not title text matching."""

    def test_spawn_guard_uses_job_filter(self, _no_environ):
        """Mock returns a session with job=integrator → spawn blocked."""
        sessions = [{"session_id": "sess-1", "session_metadata": {"job": "integrator"}}]
        list_result = _make_run_result(0, stdout=json.dumps(sessions))

        with patch("subprocess.run", return_value=list_result):
            result = _spawn_integrator_sync("my-slug", "branch-1", "abc123")

        assert result is None

    def test_spawn_guard_empty_allows_spawn(self, _no_environ):
        """Empty sessions list → spawn proceeds."""
        list_result = _make_run_result(0, stdout=json.dumps([]))
        spawn_result = _make_run_result(0, stdout='{"session_id": "new-sess"}')

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return list_result if call_count == 1 else spawn_result

        with patch("subprocess.run", side_effect=mock_run):
            result = _spawn_integrator_sync("my-slug", "branch-1", "abc123")

        assert result is not None
        assert result.get("status") == "spawned"

    def test_spawn_guard_list_failure_continues(self, _no_environ):
        """When list command fails (non-zero exit), spawn proceeds rather than blocking."""
        list_result = _make_run_result(1, stdout="", stderr="error")
        spawn_result = _make_run_result(0)

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return list_result if call_count == 1 else spawn_result

        with patch("subprocess.run", side_effect=mock_run):
            result = _spawn_integrator_sync("my-slug", "branch-1", "abc123")

        # Non-zero exit from list doesn't block spawning
        assert result is not None


class TestSpawnUsesSessionsRun:
    """Spawn command uses sessions run, not sessions start."""

    def test_spawn_uses_sessions_run(self, _no_environ):
        """Spawn command includes telec sessions run --command /next-integrate."""
        list_result = _make_run_result(0, stdout=json.dumps([]))
        spawn_result = _make_run_result(0)

        captured_cmds = []

        def mock_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return list_result if len(captured_cmds) == 1 else spawn_result

        with patch("subprocess.run", side_effect=mock_run):
            _spawn_integrator_sync("my-slug", "branch-1", "abc123")

        assert len(captured_cmds) == 2
        spawn_cmd = captured_cmds[1]
        assert "telec" in spawn_cmd
        assert "sessions" in spawn_cmd
        assert "run" in spawn_cmd
        assert "--command" in spawn_cmd
        assert "/next-integrate" in spawn_cmd
        # Must not use start with --title or --message flags
        assert "--title" not in spawn_cmd
        assert "--message" not in spawn_cmd

    def test_spawn_guard_checks_job_flag(self, _no_environ):
        """Guard command includes --job integrator flag."""
        list_result = _make_run_result(0, stdout=json.dumps([]))
        spawn_result = _make_run_result(0)

        captured_cmds = []

        def mock_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return list_result if len(captured_cmds) == 1 else spawn_result

        with patch("subprocess.run", side_effect=mock_run):
            _spawn_integrator_sync("my-slug", "branch-1", "abc123")

        assert len(captured_cmds) >= 1
        guard_cmd = captured_cmds[0]
        assert "--job" in guard_cmd
        assert "integrator" in guard_cmd
