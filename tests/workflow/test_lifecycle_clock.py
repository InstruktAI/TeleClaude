"""Functional tests for the lifecycle scheduler clock wake-up path."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from teleclaude.api_models import ProjectDTO
from teleclaude.config import config as tc_config
from teleclaude.core.next_machine.runtime.clock import SCHEDULER_TICK_MINUTE, next_minute_delay
from teleclaude.events.cartridges import lifecycle_router
from teleclaude.events.cartridges.lifecycle_router import LifecycleRouterCartridge
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext

pytestmark = pytest.mark.functional

_SPEC = "project/spec/domain/workflow"
_SOURCE = "test"
_DOMAIN = "software-development"


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_lifecycle_router_tick_wakes_each_local_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local_project = str(tmp_path / "local")
    remote_project = str(tmp_path / "remote")
    calls: list[tuple[str, str]] = []

    class _ProjectListClient:
        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def list_projects(self) -> list[ProjectDTO]:
            return [
                ProjectDTO(computer=tc_config.computer.name, name="local", path=local_project),
                ProjectDTO(computer="other-computer", name="remote", path=remote_project),
            ]

    async def _capture_runner(project_path: str, *, trigger: str, client_factory: object) -> object:
        _ = client_factory
        calls.append((project_path, trigger))
        return object()

    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _ProjectListClient)
    monkeypatch.setattr(lifecycle_router, "run_lifecycle_runner", _capture_runner)

    event = EventEnvelope(
        event=SCHEDULER_TICK_MINUTE,
        source=_SOURCE,
        level=EventLevel.WORKFLOW,
        domain=_DOMAIN,
        payload={"ticked_at": datetime.now(UTC).isoformat()},
    )

    result = await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    assert result is event
    assert calls == [(local_project, SCHEDULER_TICK_MINUTE)]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_scheduler_minute_clock_delay_anchors_to_next_wall_clock_minute() -> None:
    now = datetime(2026, 1, 1, 12, 34, 45, 500_000, tzinfo=UTC)

    assert next_minute_delay(now) == 14.5
