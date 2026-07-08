from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import HTTPException

from teleclaude.api import jobs_routes

pytestmark = pytest.mark.functional


@dataclass
class SpawnCall:
    argv: list[str]
    cwd: str | None
    start_new_session: bool | None


@pytest.mark.asyncio
async def test_run_job_endpoint_spawns_standalone_runner(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    calls: list[SpawnCall] = []

    class FakeProcess:
        pass

    def fake_popen(
        argv: list[str],
        *,
        cwd: str | None = None,
        stdout: object | None = None,
        stderr: object | None = None,
        start_new_session: bool | None = None,
    ) -> FakeProcess:
        _ = (stdout, stderr)
        calls.append(SpawnCall(argv=argv, cwd=cwd, start_new_session=start_new_session))
        return FakeProcess()

    monkeypatch.setattr(jobs_routes.subprocess, "Popen", fake_popen)

    response = await jobs_routes.run_job("daily_digest")

    assert response == snapshot(name="response")
    assert len(calls) == 1
    assert Path(calls[0].argv[0]).is_absolute()
    assert calls[0].argv[1:] == snapshot(name="runner_args")
    assert calls[0].cwd
    assert calls[0].start_new_session is True


@pytest.mark.asyncio
async def test_run_job_endpoint_reports_runner_spawn_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_popen(
        argv: list[str],
        *,
        cwd: str | None = None,
        stdout: object | None = None,
        stderr: object | None = None,
        start_new_session: bool | None = None,
    ) -> object:
        _ = (argv, cwd, stdout, stderr, start_new_session)
        raise OSError("spawn failed")

    monkeypatch.setattr(jobs_routes.subprocess, "Popen", fake_popen)

    with pytest.raises(HTTPException) as exc_info:
        await jobs_routes.run_job("daily_digest")

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail
