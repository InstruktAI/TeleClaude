"""Functional tests for creative state-machine dispatch."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.db import Db
from teleclaude.core.next_machine import create as create_machine
from teleclaude.core.next_machine._types import CreativePhase
from teleclaude.core.next_machine.create import next_create
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db

pytestmark = pytest.mark.functional

_SLUG = "creative-work"
_PROJECT_ROOT = "/repo"


@dataclass(frozen=True)
class _Session:
    session_id: str
    title: str
    subdir: str | None = None


class _CapturingDb:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = sessions

    async def list_sessions(self, *, include_closed: bool = False) -> list[_Session]:
        _ = include_closed
        return self._sessions


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _run_art_iteration(
    *,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    sessions: list[_Session],
) -> str:
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_SLUG, lineage="human:test@example.com")
    await todos_db.write_artifact(_SLUG, ARTIFACT_INPUT, "# Input", updated_by="test")

    async def _guidance(_db: Db) -> str:
        return "agent guidance"

    monkeypatch.setattr(create_machine, "compose_agent_guidance", _guidance)
    monkeypatch.setattr(create_machine, "_derive_creative_phase", lambda *_args: CreativePhase.ART_ITERATION_REQUIRED)

    output = await next_create(cast(Db, _CapturingDb(sessions)), _SLUG, str(project_root))
    return output.replace(str(project_root), _PROJECT_ROOT)


async def test_art_iteration_reuses_live_artist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    output = await _run_art_iteration(
        project_root=project_root,
        monkeypatch=monkeypatch,
        sessions=[
            _Session(
                "artist-session",
                f"/next-create-art {_SLUG}",
                subdir=f"workspace/{_SLUG}",
            )
        ],
    )

    assert output == snapshot


async def test_art_iteration_spawns_artist_without_live_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    output = await _run_art_iteration(
        project_root=project_root,
        monkeypatch=monkeypatch,
        sessions=[],
    )

    assert output == snapshot
