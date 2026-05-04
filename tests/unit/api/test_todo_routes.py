"""Characterization tests for todo workflow routes."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from typing_extensions import TypedDict

from teleclaude.api import todo_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.api_models import TodoDumpRequest
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.todos_db import TodosDb


class _ArtifactSnapshot(TypedDict, total=False):
    digest: str
    produced_at: str


class _ArtifactsSnapshot(TypedDict, total=False):
    requirements: _ArtifactSnapshot


class _TodoStateSnapshot(TypedDict, total=False):
    lifecycle_phase: str
    artifacts: _ArtifactsSnapshot


def _requirements_artifact(state: _TodoStateSnapshot) -> _ArtifactSnapshot:
    artifacts = state.get("artifacts", {})
    return artifacts.get("requirements", {})


async def async_begin() -> AsyncIterator[None]:
    """Async generator that mimics session.begin() context manager."""
    yield


@asynccontextmanager
async def _async_ctx(obj: object) -> AsyncGenerator[object]:
    """Wrap an object as an async context manager."""
    yield obj


class _TodoIntegrateReceipt(TypedDict):
    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str


def _identity(session_id: str = "sess-1") -> CallerIdentity:
    return CallerIdentity(
        session_id=session_id,
        system_role=None,
        human_role=None,
        tmux_session_name=None,
    )


class TestTodoRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_create_uses_default_cwd_when_request_omits_it(self) -> None:
        """Todo creation falls back to the configured default working directory."""
        config_stub = SimpleNamespace(computer=SimpleNamespace(default_working_dir="/repo"))
        mock_ops = MagicMock()
        mock_ops.submit_todo_create = AsyncMock(
            return_value={
                "operation_id": "op-1",
                "kind": "todo_create",
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-1",
            }
        )

        with (
            patch("teleclaude.api.todo_routes.config", config_stub),
            patch("teleclaude.api.todo_routes.get_operations_service", return_value=mock_ops),
        ):
            response = await todo_routes.todo_create(
                slug="chartest-api-routes",
                cwd=None,
                client_request_id=None,
                _identity=_identity(),
            )

        assert response["operation_id"] == "op-1"
        mock_ops.submit_todo_create.assert_awaited_once()
        call_kwargs = mock_ops.submit_todo_create.call_args.kwargs
        assert call_kwargs["cwd"] == "/repo"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_work_requires_explicit_cwd(self) -> None:
        """Todo work submissions reject requests without a working directory."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_work(
                slug="chartest-api-routes", cwd=None, client_request_id=None, identity=_identity()
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_integrate_requires_cwd(self) -> None:
        """Todo integrate submissions reject requests without a working directory."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_integrate(slug="chartest-api-routes", cwd=None, identity=_identity())

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_integrate_returns_202_receipt(self) -> None:
        """Todo integrate should submit an operation receipt instead of blocking inline."""
        receipt: _TodoIntegrateReceipt = {
            "operation_id": "op-1",
            "kind": "todo_integrate",
            "state": "queued",
            "poll_after_ms": 250,
            "status_path": "/operations/op-1",
            "recovery_command": "telec operations get op-1",
        }
        operations = MagicMock()
        operations.submit_todo_integrate = AsyncMock(return_value=receipt)
        todo_integrate = cast(Callable[..., Awaitable[_TodoIntegrateReceipt]], todo_routes.todo_integrate)
        integrate_route = next(
            route
            for route in todo_routes.router.routes
            if isinstance(route, APIRoute) and route.path == "/todos/integrate"
        )

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=operations):
            response = await todo_integrate(
                slug="chartest-api-routes",
                cwd="/repo",
                client_request_id="req-1",
                identity=_identity(),
            )

        assert integrate_route.status_code == 202
        assert response == receipt
        operations.submit_todo_integrate.assert_awaited_once_with(
            slug="chartest-api-routes",
            cwd="/repo",
            caller_session_id="sess-1",
            client_request_id="req-1",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_set_deps_returns_409_for_circular_dependency(self) -> None:
        """Dependency updates reject cycles discovered by the roadmap graph helper."""
        mock_db = AsyncMock()
        mock_db.slug_in_roadmap = AsyncMock(return_value=True)
        mock_db.load_deps = AsyncMock(return_value={"chartest-api-routes": []})

        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes.detect_circular_dependency", return_value=["a", "b", "a"]),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_set_deps(
                    slug="chartest-api-routes",
                    after=["base-task"],
                    cwd="/repo",
                    _identity=_identity(),
                )

        assert exc_info.value.status_code == 409

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_returns_404_when_slug_not_in_roadmap(self) -> None:
        """Artifact writes reject unknown slugs instead of materializing roadmap rows."""
        mock_db = AsyncMock()
        mock_db.slug_in_roadmap = AsyncMock(return_value=False)

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.write_artifact(
                    slug="missing-slug",
                    name="requirements",
                    content="content",
                    cwd="/repo",
                    updated_by="tester",
                )

        assert exc_info.value.status_code == 404
        mock_db.write_artifact.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_does_not_auto_progress_phase(self, tmp_path: Path) -> None:
        """Artifact writes preserve content only; lifecycle authority stays on stamps."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug="my-slug",
                    name="requirements",
                    content="draft requirements",
                    cwd="/repo",
                    updated_by="tester",
                )

            state = await database.read_state("my-slug")
            assert response.status == "ok"
            assert state is not None
            snapshot = cast(_TodoStateSnapshot, state)
            assert snapshot["lifecycle_phase"] == "input_assessment"
            requirements = _requirements_artifact(snapshot)
            assert requirements.get("digest", "")
            assert requirements.get("produced_at", "") == ""
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_defaults_updated_by_when_omitted(self, tmp_path: Path) -> None:
        """Route-level artifact writes record their command path when updated_by is omitted."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug="my-slug",
                    name="requirements",
                    content="draft requirements",
                    cwd="/repo",
                    updated_by=None,
                )

            assert response.status == "ok"
            conn = sqlite3.connect(str(tmp_path / "todos.db"))
            try:
                row = conn.execute(
                    "SELECT updated_by FROM todo_artifacts WHERE slug = ? AND name = ?",
                    ("my-slug", "requirements"),
                ).fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row[0] == "api.todo.write_artifact"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_requirements_ready_advances_to_requirements_review(self, tmp_path: Path) -> None:
        """The requirements_ready stamp is the authoritative completion signal for discovery."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
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
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.stamp(
                    slug="my-slug",
                    stamp_type="requirements_ready",
                    value="",
                    phase=None,
                    cwd="/repo",
                    identity=_identity(),
                )

            state = await database.read_state("my-slug")
            assert response.status == "ok"
            assert state is not None
            snapshot = cast(_TodoStateSnapshot, state)
            assert snapshot["lifecycle_phase"] == "requirements_review"
            requirements = _requirements_artifact(snapshot)
            assert requirements.get("produced_at", "")
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_requirements_ready_rejects_missing_artifact(self, tmp_path: Path) -> None:
        """requirements_ready stamp must reject when requirements artifact does not exist."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="requirements_ready",
                        value="",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_plan_ready_rejects_missing_artifact(self, tmp_path: Path) -> None:
        """plan_ready stamp must reject when implementation-plan artifact does not exist."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "plan_drafting"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="plan_ready",
                        value="",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_requirements_ready_rejects_wrong_phase(self, tmp_path: Path) -> None:
        """requirements_ready stamp must reject when lifecycle phase is not input_assessment/triangulation."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "plan_drafting"})
            await database.write_artifact("my-slug", "requirements", "some requirements")
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="requirements_ready",
                        value="",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_plan_ready_advances_to_plan_review(self, tmp_path: Path) -> None:
        """plan_ready stamp advances from plan_drafting to plan_review."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state(
                "my-slug",
                {
                    "lifecycle_phase": "plan_drafting",
                    "test_spec_review": {"verdict": "approve"},
                },
            )
            await database.write_artifact("my-slug", "implementation-plan", "the plan")
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.stamp(
                    slug="my-slug",
                    stamp_type="plan_ready",
                    value="",
                    phase=None,
                    cwd="/repo",
                    identity=_identity(),
                )

            state = await database.read_state("my-slug")
            assert response.status == "ok"
            assert state is not None
            snapshot = cast(_TodoStateSnapshot, state)
            assert snapshot["lifecycle_phase"] == "plan_review"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_writes_lifecycle_phase_and_returns_updated_state(self) -> None:
        """mark-phase writes the canonical lifecycle phase and returns updated state."""
        with patch(
            "teleclaude.api.todo_routes.mark_phase_state",
            return_value={"lifecycle_phase": PreparePhase.PREPARED.value, "kind": "bug"},
        ) as mock_mark:
            response = await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase=PreparePhase.PREPARED.value,
                cwd="/repo",
            )

        mock_mark.assert_called_once_with("/repo", "chartest-api-routes", PreparePhase.PREPARED.value)
        assert isinstance(response, dict)
        assert response.get("lifecycle_phase") == PreparePhase.PREPARED.value
        assert response.get("kind") == "bug"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_writes_work_target_when_prerequisites_hold(self) -> None:
        """Work lifecycle targets persist through the canonical lifecycle field."""
        with patch(
            "teleclaude.api.todo_routes.mark_phase_state",
            return_value={"lifecycle_phase": WorkPhase.BUILD_STARTED.value},
        ) as mock_mark:
            response = await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase=WorkPhase.BUILD_STARTED.value,
                cwd="/repo",
            )

        mock_mark.assert_called_once_with("/repo", "chartest-api-routes", WorkPhase.BUILD_STARTED.value)
        assert isinstance(response, dict)
        assert response.get("lifecycle_phase") == WorkPhase.BUILD_STARTED.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_logs_target_and_result(self, caplog: pytest.LogCaptureFixture) -> None:
        """mark-phase emits an operator-facing provenance log with target and result."""
        with (
            patch(
                "teleclaude.api.todo_routes.mark_phase_state",
                return_value={"lifecycle_phase": PreparePhase.PREPARED.value},
            ),
            caplog.at_level("INFO"),
        ):
            await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase=PreparePhase.PREPARED.value,
                cwd="/repo",
            )

        assert "todo mark-phase applied" in caplog.text

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_dump_prepped_records_updated_by_on_plan_artifact(self, tmp_path: Path) -> None:
        """Prepped dumps persist implementation-plan provenance on the artifact row."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            request = TodoDumpRequest(
                slug="my-slug",
                content="plan content",
                kind="prepped",
                cwd="/repo",
            )
            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.apply_prepared_state", return_value={"lifecycle_phase": "prepared"}),
            ):
                response = await todo_routes.todo_dump(request)

            assert response.status == "ok"
            conn = sqlite3.connect(str(tmp_path / "todos.db"))
            try:
                row = conn.execute(
                    "SELECT updated_by FROM todo_artifacts WHERE slug = ? AND name = ?",
                    ("my-slug", "implementation-plan"),
                ).fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row[0] == "api.todo.dump.prepped"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_remove_returns_receipt(self) -> None:
        """POST /todos/remove returns a 202 receipt via the operations service."""
        mock_operations = AsyncMock()
        mock_operations.submit_todo_remove = AsyncMock(
            return_value={
                "operation_id": "op-123",
                "kind": "todo_remove",
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-123",
                "recovery_command": "telec operations get op-123",
            }
        )

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=mock_operations):
            response = await todo_routes.todo_remove(
                slug="test-slug",
                cwd="/repo",
                client_request_id="req-1",
                identity=MagicMock(session_id="session-1"),
            )

        assert response["operation_id"] == "op-123"
        assert response["kind"] == "todo_remove"
        mock_operations.submit_todo_remove.assert_awaited_once_with(
            slug="test-slug",
            cwd="/repo",
            caller_session_id="session-1",
            client_request_id="req-1",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_dump_persists_draft_kind_in_state(self, tmp_path: Path) -> None:
        """POST /todos/dump with kind='draft' must persist kind='draft' in the DB state record."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                request = TodoDumpRequest(slug="my-draft", content="idea", kind="draft", cwd="/repo")
                response = await todo_routes.todo_dump(request)

            assert response.status == "ok"
            state = await database.read_state("my-draft")
            assert state is not None
            assert state["kind"] == "draft"
            assert state["lifecycle_phase"] == "draft"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_dump_notifies_via_on_committed_after_transaction(self) -> None:
        """todo_dump calls the public on_committed interface, not _on_mutation directly."""
        mock_db = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(begin=MagicMock(return_value=_async_ctx(None))))
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_db._session = MagicMock(return_value=session_ctx)
        mock_db.read_state = AsyncMock(return_value=None)
        mock_db.add_to_roadmap = AsyncMock()
        mock_db.write_state = AsyncMock()
        mock_db.write_artifact = AsyncMock()
        mock_db.on_committed = MagicMock()

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            request = TodoDumpRequest(slug="my-draft", content="idea", kind="draft", cwd="/repo")
            await todo_routes.todo_dump(request)

        mock_db.on_committed.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_split_notifies_via_on_committed_after_transaction(self) -> None:
        """todo_split calls the public on_committed interface, not _on_mutation directly."""
        mock_db = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(begin=MagicMock(return_value=_async_ctx(None))))
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_db._session = MagicMock(return_value=session_ctx)
        # First call: parent lookup returns existing state; subsequent calls return None (child doesn't exist)
        mock_db.read_state = AsyncMock(side_effect=[{"current": "pending", "breakdown": None}, None])
        mock_db.read_artifact = AsyncMock(return_value=None)
        mock_db.add_to_roadmap = AsyncMock()
        mock_db.write_state = AsyncMock()
        mock_db.on_committed = MagicMock()

        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes.StateWriter") as mock_sw,
        ):
            mock_writer = MagicMock()
            mock_writer.state = MagicMock(breakdown=None)
            mock_writer.commit = AsyncMock()
            mock_sw.return_value = mock_writer

            await todo_routes.todo_split(slug="parent", children=["child-1"], cwd="/repo")

        mock_db.on_committed.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_rejects_unknown_phase_value_with_400(self) -> None:
        """Unknown phase values yield HTTP 400 and list both enums' valid values."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase="not_a_real_phase",
                cwd="/repo",
            )

        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert isinstance(detail, str)
        assert PreparePhase.PREPARED.value in detail
        assert WorkPhase.BUILD_STARTED.value in detail

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_prepare_pair_resolves_agent_and_native_from_session(self, tmp_path: Path) -> None:
        """prepare_pair stamp resolves agent + native_session_id from session records and persists all four slot fields."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})

            session_a = SimpleNamespace(active_agent="claude", native_session_id="native-a-uuid")
            session_b = SimpleNamespace(active_agent="codex", native_session_id="native-b-uuid")

            async def fake_get_session(session_id: str) -> object:
                return {"sid-a": session_a, "sid-b": session_b}.get(session_id)

            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.db.get_session", side_effect=fake_get_session),
            ):
                response = await todo_routes.stamp(
                    slug="my-slug",
                    stamp_type="prepare_pair",
                    value="slot_a:sid-a,slot_b:sid-b",
                    phase=None,
                    cwd="/repo",
                    identity=_identity(),
                )

            assert response.status == "ok"
            state = await database.read_state("my-slug")
            assert state is not None
            pair = state.get("prepare_pair")
            assert isinstance(pair, dict)
            slot_a = pair.get("slot_a", {})
            slot_b = pair.get("slot_b", {})
            assert isinstance(slot_a, dict) and isinstance(slot_b, dict)
            assert slot_a == {
                "lens": "A",
                "session_id": "sid-a",
                "native_session_id": "native-a-uuid",
                "agent": "claude",
            }
            assert slot_b == {
                "lens": "B",
                "session_id": "sid-b",
                "native_session_id": "native-b-uuid",
                "agent": "codex",
            }
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_prepare_pair_rejects_unknown_session(self, tmp_path: Path) -> None:
        """prepare_pair stamp returns 422 when a session_id is not found in the sessions table."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})

            async def fake_get_session(_session_id: str) -> object:
                return None

            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.db.get_session", side_effect=fake_get_session),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="prepare_pair",
                        value="slot_a:sid-a,slot_b:sid-b",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
                assert "unknown session" in str(exc_info.value.detail)
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_prepare_pair_rejects_session_without_native_id(self, tmp_path: Path) -> None:
        """Slot would not survive TC purge — reject when native_session_id is missing."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})

            session_a = SimpleNamespace(active_agent="claude", native_session_id="native-a")
            session_b = SimpleNamespace(active_agent="codex", native_session_id=None)

            async def fake_get_session(session_id: str) -> object:
                return {"sid-a": session_a, "sid-b": session_b}.get(session_id)

            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.db.get_session", side_effect=fake_get_session),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="prepare_pair",
                        value="slot_a:sid-a,slot_b:sid-b",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
                assert "native_session_id" in str(exc_info.value.detail)
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_prepare_pair_rejects_session_without_active_agent(self, tmp_path: Path) -> None:
        """Slot agent must be resolvable — reject when active_agent is missing."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})

            session_a = SimpleNamespace(active_agent=None, native_session_id="native-a")
            session_b = SimpleNamespace(active_agent="codex", native_session_id="native-b")

            async def fake_get_session(session_id: str) -> object:
                return {"sid-a": session_a, "sid-b": session_b}.get(session_id)

            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.db.get_session", side_effect=fake_get_session),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="prepare_pair",
                        value="slot_a:sid-a,slot_b:sid-b",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
                assert "active_agent" in str(exc_info.value.detail)
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stamp_prepare_pair_rejects_incomplete_value(self, tmp_path: Path) -> None:
        """Compound value must contain both slot_a and slot_b — reject when one is missing."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "input_assessment"})

            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                with pytest.raises(HTTPException) as exc_info:
                    await todo_routes.stamp(
                        slug="my-slug",
                        stamp_type="prepare_pair",
                        value="slot_a:sid-a",
                        phase=None,
                        cwd="/repo",
                        identity=_identity(),
                    )
                assert exc_info.value.status_code == 422
                assert "slot_a and slot_b" in str(exc_info.value.detail)
        finally:
            await database.close()
