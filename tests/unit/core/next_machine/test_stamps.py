"""Unit tests for local todo stamp application."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import CreativePhase
from teleclaude.core.next_machine.create import _derive_creative_phase
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import PreparePair, PreparePairSlot

_STAMPS = "teleclaude.core.next_machine.stamps"


class _SessionDb:
    def __init__(self, sessions: Mapping[str, object]) -> None:
        self._sessions = sessions

    def is_initialized(self) -> bool:
        return True

    async def initialize(self) -> None:
        return None

    async def get_session(self, session_id: str) -> object | None:
        return self._sessions.get(session_id)


async def _make_db(tmp_path: Path) -> TodosDb:
    database = TodosDb(str(tmp_path / "todos.db"))
    await database.initialize()
    await database.add_to_roadmap("my-slug")
    return database


@pytest.mark.unit
@pytest.mark.asyncio
async def test_requirements_ready_advances_to_requirements_review(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state(
            "my-slug",
            {
                "lifecycle_phase": "triangulation",
                "artifacts": {
                    "input": {"digest": "sha256-abc", "produced_at": "2026-01-01T00:00:00+00:00"},
                },
            },
        )
        await database.write_artifact("my-slug", "requirements", "ready requirements")
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            state = await apply_todo_stamp(
                cwd="/repo",
                slug="my-slug",
                stamp_type="requirements_ready",
                value="true",
            )

        assert state["lifecycle_phase"] == "requirements_review"
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_requirements_ready_rejects_missing_artifact(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            with pytest.raises(StateMutationError, match="requirements artifact missing"):
                await apply_todo_stamp(
                    cwd="/repo",
                    slug="my-slug",
                    stamp_type="requirements_ready",
                    value="true",
                )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_pair_persists_native_identity(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    sessions = _SessionDb(
        {
            "sid-a": SimpleNamespace(active_agent="claude", native_session_id="native-a"),
            "sid-b": SimpleNamespace(active_agent="codex", native_session_id="native-b"),
        }
    )
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_db", new=AsyncMock(return_value=sessions)),
        ):
            state = await apply_todo_stamp(
                cwd="/repo",
                slug="my-slug",
                stamp_type="prepare_pair",
                value="slot_a:sid-a,slot_b:sid-b",
            )

        pair = state.get("prepare_pair")
        assert isinstance(pair, dict)
        assert PreparePair.model_validate(pair) == PreparePair(
            slot_a=PreparePairSlot(
                session_id="sid-a",
                native_session_id="native-a",
                agent="claude",
                lens="A",
            ),
            slot_b=PreparePairSlot(
                session_id="sid-b",
                native_session_id="native-b",
                agent="codex",
                lens="B",
            ),
        )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_pair_rejects_unknown_session(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_db", new=AsyncMock(return_value=_SessionDb({}))),
        ):
            with pytest.raises(StateMutationError, match="unknown session"):
                await apply_todo_stamp(
                    cwd="/repo",
                    slug="my-slug",
                    stamp_type="prepare_pair",
                    value="slot_a:sid-a,slot_b:sid-b",
                )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deferrals_processed_stamp_clears_pending_deferrals_route(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
        await database.write_artifact("my-slug", "deferrals", "- defer follow-up")
        assert await database.has_pending_deferrals("my-slug") is True

        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            await apply_todo_stamp(
                cwd="/repo",
                slug="my-slug",
                stamp_type="deferrals_processed",
                value="true",
            )

        assert await database.has_pending_deferrals("my-slug") is False
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creative_gate_stamp_advances_derived_creative_route(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    workspace_dir = tmp_path / "workspace" / "my-slug"
    art_dir = workspace_dir / "art"
    art_dir.mkdir(parents=True)
    (art_dir / "hero.png").write_text("image placeholder", encoding="utf-8")

    try:
        await database.write_state(
            "my-slug",
            {
                "lifecycle_phase": "draft",
                "creative": {"design_spec": {"confirmed": True}},
            },
        )
        before_state = await database.read_state("my-slug")
        assert isinstance(before_state, dict)
        before_creative = before_state["creative"]
        assert isinstance(before_creative, dict)
        assert (
            _derive_creative_phase(workspace_dir, has_design_spec=True, creative=before_creative)
            == CreativePhase.ART_PENDING_APPROVAL
        )

        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            state = await apply_todo_stamp(
                cwd="/repo",
                slug="my-slug",
                stamp_type="creative_art_approved",
                value="true",
            )

        creative = state["creative"]
        assert isinstance(creative, dict)
        assert (
            _derive_creative_phase(workspace_dir, has_design_spec=True, creative=creative)
            == CreativePhase.VISUAL_DRAFTS_REQUIRED
        )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_complete_requires_owning_worker_session(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "build_started"})
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            with pytest.raises(PermissionError, match="requires a TeleClaude worker session"):
                await apply_todo_stamp(
                    cwd="/repo",
                    slug="my-slug",
                    stamp_type="build_complete",
                    value="true",
                )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_complete_rejects_wrong_working_slug(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    sessions = _SessionDb({"builder": SimpleNamespace(working_slug="other-slug")})
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "build_started"})
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_db", new=AsyncMock(return_value=sessions)),
        ):
            with pytest.raises(PermissionError, match="requires caller session builder"):
                await apply_todo_stamp(
                    cwd="/repo",
                    slug="my-slug",
                    stamp_type="build_complete",
                    value="true",
                    caller_session_id="builder",
                )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_complete_validates_evidence_and_advances(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    sessions = _SessionDb({"builder": SimpleNamespace(working_slug="my-slug")})
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "build_started"})
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_db", new=AsyncMock(return_value=sessions)),
            patch(f"{_STAMPS}.resolve_state_root", return_value=str(tmp_path)),
            patch(f"{_STAMPS}.has_build_commits_beyond_main", return_value=True),
            patch(f"{_STAMPS}.run_build_gates", return_value=(True, "passed")),
        ):
            state = await apply_todo_stamp(
                cwd=str(tmp_path),
                slug="my-slug",
                stamp_type="build_complete",
                value="true",
                caller_session_id="builder",
            )

        assert state["lifecycle_phase"] == "build_complete"
        assert state["build_completed_at"]
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_complete_rejects_gate_failure(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    sessions = _SessionDb({"builder": SimpleNamespace(working_slug="my-slug")})
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "build_started"})
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_db", new=AsyncMock(return_value=sessions)),
            patch(f"{_STAMPS}.resolve_state_root", return_value=str(tmp_path)),
            patch(f"{_STAMPS}.has_build_commits_beyond_main", return_value=True),
            patch(f"{_STAMPS}.run_build_gates", return_value=(False, "gate failed")),
        ):
            with pytest.raises(StateMutationError, match="build gates failed"):
                await apply_todo_stamp(
                    cwd=str(tmp_path),
                    slug="my-slug",
                    stamp_type="build_complete",
                    value="true",
                    caller_session_id="builder",
                )
    finally:
        await database.close()
