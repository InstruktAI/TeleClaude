"""Characterization tests for teleclaude.deployment.executor."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

import teleclaude.deployment.executor as executor


class _ExitCalled(SystemExit):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.kill_called = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    async def wait(self) -> None:
        return None

    def kill(self) -> None:
        self.kill_called = True


def _patch_status_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Mapping[str, object]]:
    statuses: list[Mapping[str, object]] = []

    async def fake_set_status(
        _redis: object,
        _status_key: str,
        payload: Mapping[str, object],
    ) -> None:
        statuses.append(payload)

    monkeypatch.setattr(executor, "_set_status", fake_set_status)
    return statuses


def _patch_subprocesses(monkeypatch: pytest.MonkeyPatch, processes: list[_FakeProcess]) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    async def fake_create_subprocess_exec(*args: Any, **_kwargs: Any) -> _FakeProcess:
        calls.append(args)
        return processes.pop(0)

    monkeypatch.setattr(executor.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    return calls


def _patch_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor.os, "_exit", lambda code: (_ for _ in ()).throw(_ExitCalled(code)))


async def _get_redis() -> object:
    return object()


async def test_execute_update_alpha_runs_pull_migrations_install_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = _patch_status_capture(monkeypatch)
    calls = _patch_subprocesses(monkeypatch, [_FakeProcess(), _FakeProcess()])
    _patch_exit(monkeypatch)
    monkeypatch.setattr(executor, "_read_version_from_pyproject", lambda: "9.9.9")
    monkeypatch.setattr(
        executor,
        "run_migrations",
        lambda from_ver, to_ver: {
            "migrations_run": 1,
            "migrations_skipped": 0,
            "error": None,
            "planned_migrations": [f"{from_ver}->{to_ver}"],
        },
    )
    monkeypatch.setattr(executor.config.computer, "name", "test-node")

    with pytest.raises(_ExitCalled) as exc_info:
        await executor.execute_update(
            "alpha",
            {"from_version": "1.0.0", "version": ""},
            get_redis=_get_redis,
        )

    assert exc_info.value.code == 42
    assert calls == [
        ("git", "pull", "--ff-only", "origin", "main"),
        ("make", "install"),
    ]
    assert [status["status"] for status in statuses] == ["updating", "migrating", "installing", "restarting"]


async def test_execute_update_stops_after_git_pull_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = _patch_status_capture(monkeypatch)
    calls = _patch_subprocesses(monkeypatch, [_FakeProcess(returncode=1, stderr=b"merge blocked")])
    run_migrations_called = False

    def fake_run_migrations(
        _from_ver: str, _to_ver: str
    ) -> dict[str, Any]:  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
        nonlocal run_migrations_called
        run_migrations_called = True
        return {"migrations_run": 0, "migrations_skipped": 0, "error": None, "planned_migrations": []}

    monkeypatch.setattr(executor, "run_migrations", fake_run_migrations)
    monkeypatch.setattr(executor.config.computer, "name", "test-node")

    await executor.execute_update(
        "alpha",
        {"from_version": "1.0.0", "version": ""},
        get_redis=_get_redis,
    )

    assert calls == [("git", "pull", "--ff-only", "origin", "main")]
    assert run_migrations_called is False
    assert statuses[-1] == {"status": "update_failed", "error": "git pull --ff-only failed: merge blocked"}


async def test_execute_update_non_alpha_checks_out_version_tag_before_install(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = _patch_status_capture(monkeypatch)
    calls = _patch_subprocesses(monkeypatch, [_FakeProcess(), _FakeProcess(), _FakeProcess()])
    _patch_exit(monkeypatch)
    monkeypatch.setattr(
        executor,
        "run_migrations",
        lambda _from_ver, _to_ver: {
            "migrations_run": 0,
            "migrations_skipped": 0,
            "error": None,
            "planned_migrations": [],
        },
    )
    monkeypatch.setattr(executor.config.computer, "name", "test-node")

    with pytest.raises(_ExitCalled):
        await executor.execute_update(
            "stable",
            {"from_version": "1.0.0", "version": "1.2.3"},
            get_redis=_get_redis,
        )

    assert calls == [
        ("git", "fetch", "--tags"),
        ("git", "checkout", "v1.2.3"),
        ("make", "install"),
    ]
    assert statuses[-1]["status"] == "restarting"
