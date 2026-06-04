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
from syrupy.assertion import SnapshotAssertion
from typing_extensions import TypedDict

from teleclaude.api import todo_routes
from teleclaude.api.auth import (
    CallerIdentity,
    clearance_todos_reactivate,
    clearance_todos_reconcile,
)
from teleclaude.api.kind_mapper import KIND_BUG, KIND_FEATURE
from teleclaude.api_models import TodoDumpRequest
from teleclaude.constants import (
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
)
from teleclaude.core.todos_db import TodosDb

_EMPTY = ""
_MY_SLUG = "my-slug"
_REPO_CWD = "/repo"
_SRC_APP = "src/app.py"
_HEAD_SHA = "head-sha"
_STATUS_OK = "ok"
_TRASHED_SLUG = "trashed"
_RESTORED_SLUG = "restored-slug"
_DRAFT_KIND = "draft"
_REFACTOR_KIND = "refactor"
_TODO_KIND = "todo"
_PLAN_DRAFTING = "plan_drafting"
_PREPARED = "prepared"
_SPLIT_INPUT_CONTENT = "split input"
_STALE_REQUIREMENTS_CONTENT = "stale requirements"
_REJECTED_HOLDER_INPUT_CONTENT = "changed input"
_CREATE_OPERATION_ID = "op-1"
_REMOVE_OPERATION_ID = "op-123"
_RENAME_OPERATION_ID = "op-rename-123"
_TODO_REMOVE_KIND = "todo_remove"
_TODO_RENAME_KIND = "todo_rename"
_UPDATED_BY_WRITE_ARTIFACT = "api.todo.write_artifact"
_UPDATED_BY_PREPPED_CREATE = "api.todo.create.prepped"
_WORKFLOW_TODO_CREATED = "workflow.todo.created"
_CREATION_MODE_PICKUP = "pickup"
_CREATION_MODE_SILENT = "silent"


class _ArtifactSnapshot(TypedDict, total=False):
    digest: str
    produced_at: str
    codebase_sha_at_write: str
    referenced_paths: list[str]
    upstream_digests: dict[str, str]


class _ArtifactsSnapshot(TypedDict, total=False):
    prd: _ArtifactSnapshot
    requirements: _ArtifactSnapshot


class _ApprovalSnapshot(TypedDict, total=False):
    approved: bool


class _ApprovalsSnapshot(TypedDict, total=False):
    prd_approved: _ApprovalSnapshot


class _TodoStateSnapshot(TypedDict, total=False):
    lifecycle_phase: str
    artifacts: _ArtifactsSnapshot
    approvals: _ApprovalsSnapshot


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
    def test_local_mutation_routes_are_not_exposed(self) -> None:
        paths = {route.path for route in todo_routes.router.routes if isinstance(route, APIRoute)}
        assert "/todos/stamp/{slug}" not in paths
        assert "/todos/mark-phase/{slug}" not in paths

    @pytest.mark.unit
    def test_reconcile_route_is_bound_to_clearance_dependency(self) -> None:
        """Reconcile is a mutating lifecycle endpoint — the route MUST carry
        Depends(clearance_todos_reconcile). The dual-factor / RBAC boundary
        documented at the top of todo_routes.py is delegated to FastAPI's
        Depends graph; removing the binding silently de-authorizes the
        endpoint. Use the function reference (not a path literal) so this
        survives URL refactors.
        """
        route = next(
            r for r in todo_routes.router.routes if isinstance(r, APIRoute) and r.endpoint is todo_routes.todo_reconcile
        )
        bound = {dep.call for dep in route.dependant.dependencies}
        assert clearance_todos_reconcile in bound

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_show_route_accepts_include_artifact_content(self, tmp_path: Path) -> None:
        """The show route keeps artifact bodies behind an explicit query flag."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap(_MY_SLUG)
            await database.write_state(_MY_SLUG, {"lifecycle_phase": "draft"})
            await database.write_artifact(_MY_SLUG, ARTIFACT_PRD, "prd body")

            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                default_payload = await todo_routes.todo_show(_MY_SLUG, cwd=_REPO_CWD)
                content_payload = await todo_routes.todo_show(
                    _MY_SLUG,
                    cwd=_REPO_CWD,
                    include_artifact_content=True,
                )

            assert "artifact_content" not in default_payload
            assert content_payload["artifacts"] == [ARTIFACT_PRD]
            assert content_payload["artifact_content"] == {ARTIFACT_PRD: "prd body"}
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_create_uses_default_cwd_when_request_omits_it(self) -> None:
        """Todo creation falls back to the configured default working directory."""
        config_stub = SimpleNamespace(computer=SimpleNamespace(default_working_dir=_REPO_CWD))
        mock_ops = MagicMock()
        mock_ops.submit_todo_create = AsyncMock(
            return_value={
                "operation_id": _CREATE_OPERATION_ID,
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

        assert response["operation_id"] == _CREATE_OPERATION_ID
        mock_ops.submit_todo_create.assert_awaited_once()
        call_kwargs = mock_ops.submit_todo_create.call_args.kwargs
        assert call_kwargs["cwd"] == _REPO_CWD

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
    async def test_todo_rename_returns_202_receipt(self) -> None:
        """Todo rename submits a durable operation instead of running inline."""
        receipt = {
            "operation_id": _RENAME_OPERATION_ID,
            "kind": _TODO_RENAME_KIND,
            "state": "queued",
            "poll_after_ms": 250,
            "status_path": "/operations/op-rename-123",
            "recovery_command": "telec operations get op-rename-123",
        }
        operations = MagicMock()
        operations.submit_todo_rename = AsyncMock(return_value=receipt)
        rename_route = next(
            route
            for route in todo_routes.router.routes
            if isinstance(route, APIRoute) and route.path == "/todos/rename"
        )

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=operations):
            response = await todo_routes.todo_rename(
                old_slug="old-slug",
                new_slug="new-slug",
                cwd="/repo",
                client_request_id="req-1",
                identity=_identity(),
            )

        assert rename_route.status_code == 202
        assert response == receipt
        operations.submit_todo_rename.assert_awaited_once_with(
            old_slug="old-slug",
            new_slug="new-slug",
            cwd="/repo",
            caller_session_id="sess-1",
            client_request_id="req-1",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_rename_requires_cwd(self) -> None:
        """Todo rename submissions reject requests without a working directory."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_rename(
                old_slug="old-slug",
                new_slug="new-slug",
                cwd=None,
                client_request_id=None,
                identity=_identity(),
            )

        assert exc_info.value.status_code == 400

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
    async def test_write_artifact_refuses_retired_test_specs(self) -> None:
        """Retired artifact kinds are rejected at the write boundary before any DB work."""
        mock_db = AsyncMock()

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.write_artifact(
                    slug=_MY_SLUG,
                    name="test-specs",
                    content="# Gherkin\n",
                    cwd=_REPO_CWD,
                    updated_by="tester",
                )

        assert exc_info.value.status_code == 422
        mock_db.write_artifact.assert_not_awaited()
        mock_db.slug_in_roadmap.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_refuses_retired_spec_review_findings(self) -> None:
        mock_db = AsyncMock()
        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.write_artifact(
                    slug=_MY_SLUG,
                    name="spec-review-findings",
                    content="findings",
                    cwd=_REPO_CWD,
                    updated_by="tester",
                )
        assert exc_info.value.status_code == 422
        mock_db.write_artifact.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_refuses_unknown_name(self) -> None:
        mock_db = AsyncMock()
        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.write_artifact(
                    slug=_MY_SLUG,
                    name="not-a-real-kind",
                    content="x",
                    cwd=_REPO_CWD,
                    updated_by="tester",
                )
        assert exc_info.value.status_code == 422
        mock_db.write_artifact.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_does_not_auto_progress_phase(self, tmp_path: Path) -> None:
        """Artifact writes preserve content only; lifecycle authority stays on stamps."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap(_MY_SLUG)
            await database.write_state(_MY_SLUG, {"lifecycle_phase": _PLAN_DRAFTING})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug=_MY_SLUG,
                    name=ARTIFACT_REQUIREMENTS,
                    content="draft requirements",
                    cwd=_REPO_CWD,
                    updated_by="tester",
                )

            state = await database.read_state(_MY_SLUG)
            assert response.status == _STATUS_OK
            assert state is not None
            snapshot = cast(_TodoStateSnapshot, state)
            assert snapshot["lifecycle_phase"] == _PLAN_DRAFTING
            requirements = _requirements_artifact(snapshot)
            assert requirements.get("digest", _EMPTY)
            assert requirements.get("produced_at", _EMPTY)
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_defaults_updated_by_when_omitted(self, tmp_path: Path) -> None:
        """Route-level artifact writes record their command path when updated_by is omitted."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap(_MY_SLUG)
            await database.write_state(_MY_SLUG, {"lifecycle_phase": _PLAN_DRAFTING})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug=_MY_SLUG,
                    name=ARTIFACT_REQUIREMENTS,
                    content="draft requirements",
                    cwd=_REPO_CWD,
                    updated_by=None,
                )

            assert response.status == _STATUS_OK
            conn = sqlite3.connect(str(tmp_path / "todos.db"))
            try:
                row = conn.execute(
                    "SELECT updated_by FROM todo_artifacts WHERE slug = ? AND name = ?",
                    (_MY_SLUG, ARTIFACT_REQUIREMENTS),
                ).fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row[0] == _UPDATED_BY_WRITE_ARTIFACT
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_records_codebase_provenance_in_state(self, tmp_path: Path) -> None:
        """Route-level artifact writes sync codebase provenance into the typed state entry."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap(_MY_SLUG)
            await database.write_state(_MY_SLUG, {"schema_version": 3, "lifecycle_phase": _PLAN_DRAFTING})
            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.core.next_machine.provenance.get_origin_main_sha", return_value=_HEAD_SHA),
                patch("teleclaude.core.next_machine.provenance.extract_referenced_paths", return_value=[_SRC_APP]),
            ):
                response = await todo_routes.write_artifact(
                    slug=_MY_SLUG,
                    name=ARTIFACT_PRD,
                    content="touches src/app.py",
                    cwd=_REPO_CWD,
                    updated_by="tester",
                    codebase_sha_at_write=_HEAD_SHA,
                    referenced_paths=[_SRC_APP],
                )

            state = await database.read_state(_MY_SLUG)
            assert response.status == _STATUS_OK
            assert state is not None
            artifacts = cast(_TodoStateSnapshot, state)["artifacts"]
            prd = artifacts["prd"]
            assert prd["codebase_sha_at_write"] == _HEAD_SHA
            assert prd["referenced_paths"] == [_SRC_APP]
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_artifact_deletes_present_artifact(self, tmp_path: Path) -> None:
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap(_MY_SLUG)
            await database.write_artifact(_MY_SLUG, ARTIFACT_INPUT, "input")
            await database.write_artifact(_MY_SLUG, ARTIFACT_REQUIREMENTS, "requirements-v1")
            await database.write_artifact(_MY_SLUG, ARTIFACT_REQUIREMENTS, "requirements-v2")
            await database.write_artifact(_MY_SLUG, ARTIFACT_PRD, "prd")

            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.remove_artifact(
                    slug=_MY_SLUG,
                    name=ARTIFACT_REQUIREMENTS,
                    cwd=_REPO_CWD,
                    _identity=_identity(),
                )

            assert response.status == _STATUS_OK
            assert response.removed is True
            assert response.versions_deleted == 2
            assert set(await database.list_artifacts(_MY_SLUG)) == {ARTIFACT_INPUT, ARTIFACT_PRD}
            assert await database.artifact_versions(_MY_SLUG, ARTIFACT_REQUIREMENTS) == []
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_artifact_is_idempotent_for_missing_artifact(self) -> None:
        mock_db = AsyncMock()
        mock_db.slug_in_roadmap = AsyncMock(return_value=True)
        mock_db.delete_artifact = AsyncMock(return_value={"removed": False, "versions_deleted": 0})

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            response = await todo_routes.remove_artifact(
                slug=_MY_SLUG,
                name=ARTIFACT_REQUIREMENTS,
                cwd=_REPO_CWD,
                _identity=_identity(),
            )

        assert response.status == _STATUS_OK
        assert response.removed is False
        assert response.versions_deleted == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_artifact_refuses_input(self) -> None:
        mock_db = AsyncMock()

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.remove_artifact(
                    slug=_MY_SLUG,
                    name=ARTIFACT_INPUT,
                    cwd=_REPO_CWD,
                    _identity=_identity(),
                )

        assert exc_info.value.status_code == 400
        mock_db.delete_artifact.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_artifact_returns_404_for_unknown_slug(self) -> None:
        mock_db = AsyncMock()
        mock_db.slug_in_roadmap = AsyncMock(return_value=False)

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.remove_artifact(
                    slug="missing-slug",
                    name=ARTIFACT_REQUIREMENTS,
                    cwd=_REPO_CWD,
                    _identity=_identity(),
                )

        assert exc_info.value.status_code == 404
        mock_db.delete_artifact.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_artifact_clears_lifecycle_artifact_provenance(self, tmp_path: Path) -> None:
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap(_MY_SLUG)
            await database.write_state(
                _MY_SLUG,
                {
                    "schema_version": 3,
                    "lifecycle_phase": _PLAN_DRAFTING,
                    "approvals": {"prd_approved": {"approved": True}},
                    "artifacts": {
                        "requirements": {
                            "digest": "digest-before-remove",
                            "produced_at": "timestamp-before-remove",
                            "codebase_sha_at_write": "sha-before-remove",
                            "referenced_paths": [_SRC_APP],
                            "upstream_digests": {"prd": "upstream-before-remove"},
                        }
                    },
                },
            )
            await database.write_artifact(_MY_SLUG, ARTIFACT_REQUIREMENTS, "requirements")

            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.remove_artifact(
                    slug=_MY_SLUG,
                    name=ARTIFACT_REQUIREMENTS,
                    cwd=_REPO_CWD,
                    _identity=_identity(),
                )

            state = await database.read_state(_MY_SLUG)
            assert response.status == _STATUS_OK
            assert response.removed is True
            assert state is not None
            typed_state = cast(_TodoStateSnapshot, state)
            assert typed_state["lifecycle_phase"] == _PLAN_DRAFTING
            assert typed_state["approvals"]["prd_approved"]["approved"] is True
            requirements = typed_state["artifacts"]["requirements"]
            assert requirements["digest"] == _EMPTY
            assert requirements["produced_at"] == _EMPTY
            assert requirements["codebase_sha_at_write"] == _EMPTY
            assert requirements["referenced_paths"] == []
            assert requirements["upstream_digests"] == {}
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_prepped_records_updated_by_on_plan_artifact(self, tmp_path: Path) -> None:
        """Prepped creation requests persist implementation-plan provenance on the artifact row."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            request = TodoDumpRequest(
                slug=_MY_SLUG,
                content="plan content",
                kind="prepped",
                cwd=_REPO_CWD,
            )
            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch(
                    "teleclaude.api.todo_routes.apply_prepared_state",
                    return_value={"lifecycle_phase": _PREPARED},
                ),
                patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock),
            ):
                response = await todo_routes.todo_content_create(request)

            assert response.status == _STATUS_OK
            conn = sqlite3.connect(str(tmp_path / "todos.db"))
            try:
                row = conn.execute(
                    "SELECT updated_by FROM todo_artifacts WHERE slug = ? AND name = ?",
                    (_MY_SLUG, "implementation-plan"),
                ).fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row[0] == _UPDATED_BY_PREPPED_CREATE
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_remove_returns_receipt(self) -> None:
        """POST /todos/remove returns a 202 receipt via the operations service."""
        mock_operations = AsyncMock()
        mock_operations.submit_todo_remove = AsyncMock(
            return_value={
                "operation_id": _REMOVE_OPERATION_ID,
                "kind": _TODO_REMOVE_KIND,
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-123",
                "recovery_command": "telec operations get op-123",
            }
        )

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=mock_operations):
            response = await todo_routes.todo_remove(
                slug="test-slug",
                cwd=_REPO_CWD,
                client_request_id="req-1",
                identity=MagicMock(session_id="session-1"),
            )

        assert response["operation_id"] == _REMOVE_OPERATION_ID
        assert response["kind"] == _TODO_REMOVE_KIND
        mock_operations.submit_todo_remove.assert_awaited_once_with(
            slug="test-slug",
            cwd=_REPO_CWD,
            caller_session_id="session-1",
            client_request_id="req-1",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_persists_draft_kind_in_state(self, tmp_path: Path) -> None:
        """The content-creation route must persist kind='draft' in the DB state record."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                request = TodoDumpRequest(slug="my-draft", content="idea", kind=_DRAFT_KIND, cwd=_REPO_CWD)
                response = await todo_routes.todo_content_create(request)

            assert response.status == _STATUS_OK
            state = await database.read_state("my-draft")
            assert state is not None
            assert state["kind"] == _DRAFT_KIND
            assert state["lifecycle_phase"] == _DRAFT_KIND
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_persists_refactor_kind_in_state(self, tmp_path: Path) -> None:
        """The content-creation route must persist kind='refactor' in the DB state record."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock),
            ):
                request = TodoDumpRequest(
                    slug="my-refactor", content="refactor plan", kind=_REFACTOR_KIND, cwd=_REPO_CWD
                )
                response = await todo_routes.todo_content_create(request)

            assert response.status == _STATUS_OK
            state = await database.read_state("my-refactor")
            assert state is not None
            assert state["kind"] == _REFACTOR_KIND
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_persists_todo_kind_in_state(self, tmp_path: Path) -> None:
        """The content-creation route must persist kind='todo' in the DB state record."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock),
            ):
                request = TodoDumpRequest(slug="my-todo", content="todo content", kind=_TODO_KIND, cwd=_REPO_CWD)
                response = await todo_routes.todo_content_create(request)

            assert response.status == _STATUS_OK
            state = await database.read_state("my-todo")
            assert state is not None
            assert state["kind"] == _TODO_KIND
        finally:
            await database.close()

    def _make_content_create_mock_db(self) -> MagicMock:
        """Minimal mock TodosDb for todo creation route tests."""
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
        return mock_db

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_notifies_via_on_committed_after_transaction(self) -> None:
        """todo_content_create calls the public on_committed interface, not _on_mutation directly."""
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
            await todo_routes.todo_content_create(request)

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
        mock_db.slug_in_roadmap = AsyncMock(return_value=True)
        mock_db.slug_conflicts_non_removed = AsyncMock(return_value=False)
        mock_db.read_artifact = AsyncMock(return_value=None)
        mock_db.add_to_roadmap = AsyncMock()
        mock_db.write_state = AsyncMock()
        mock_db.on_committed = MagicMock()

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            await todo_routes.todo_split(slug="parent", children=["child-1"], cwd="/repo")

        mock_db.on_committed.assert_called()
        mock_db.write_state.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_split_leaves_parent_stateless_with_frozen_input(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        db_dir = project / ".teleclaude"
        db_dir.mkdir()
        todos_db = TodosDb(str(db_dir / "todos.db"))
        await todos_db.initialize()
        try:
            await todos_db.add_to_roadmap("parent")
            await todos_db.write_state("parent", {"lifecycle_phase": "prepared"})
            await todos_db.write_artifact("parent", ARTIFACT_INPUT, _SPLIT_INPUT_CONTENT)
            await todos_db.write_artifact("parent", ARTIFACT_REQUIREMENTS, _STALE_REQUIREMENTS_CONTENT)

            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=todos_db):
                await todo_routes.todo_split(slug="parent", children=["child-1"], cwd=str(project))

            assert await todos_db.read_state("parent") is None
            assert await todos_db.list_artifacts("parent") == [ARTIFACT_INPUT]
            assert await todos_db.read_artifact("parent", ARTIFACT_INPUT) == _SPLIT_INPUT_CONTENT
            assert await todos_db.read_artifact("child-1", ARTIFACT_INPUT) == _SPLIT_INPUT_CONTENT
            with pytest.raises(ValueError):
                await todos_db.write_artifact("parent", ARTIFACT_INPUT, _REJECTED_HOLDER_INPUT_CONTENT)
        finally:
            await todos_db.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_with_empty_content_returns_400_and_writes_nothing(self) -> None:
        """Whitespace-only content is rejected with 400 before any DB write."""
        mock_db = MagicMock()
        mock_db.read_state = AsyncMock(return_value=None)
        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            pytest.raises(HTTPException) as exc_info,
        ):
            await todo_routes.todo_content_create(TodoDumpRequest(slug=_MY_SLUG, content="   ", cwd=_REPO_CWD))
        assert exc_info.value.status_code == 400
        mock_db.add_to_roadmap.assert_not_called()
        mock_db.write_state.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_with_whitespace_only_content_returns_400_and_writes_nothing(self) -> None:
        """Newlines-and-tabs content is rejected with 400 before any DB write."""
        mock_db = MagicMock()
        mock_db.read_state = AsyncMock(return_value=None)
        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            pytest.raises(HTTPException) as exc_info,
        ):
            await todo_routes.todo_content_create(TodoDumpRequest(slug=_MY_SLUG, content="\n\n\t", cwd=_REPO_CWD))
        assert exc_info.value.status_code == 400
        mock_db.add_to_roadmap.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_emits_workflow_todo_created_once_with_partial_shape_payload(self) -> None:
        """Route emits exactly one workflow.todo.created event with the transitional partial-shape."""
        mock_db = self._make_content_create_mock_db()
        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes._sync_artifact_provenance_state", new_callable=AsyncMock),
            patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock) as mock_emit,
        ):
            await todo_routes.todo_content_create(TodoDumpRequest(slug=_MY_SLUG, content="some content", cwd=_REPO_CWD))

        mock_emit.assert_called_once()
        payload = mock_emit.call_args.kwargs["payload"]
        assert mock_emit.call_args.kwargs["event"] == _WORKFLOW_TODO_CREATED
        assert payload["slug"] == _MY_SLUG
        assert payload["kind"] == KIND_FEATURE
        assert payload["creation_mode"] == _CREATION_MODE_PICKUP
        assert payload["pickup_requested"] is True
        _ = payload["lifecycle_phase"]
        _ = payload["created_at"]
        _ = payload["project_path"]
        assert "todo_id" not in payload
        assert "project_id" not in payload
        assert "created_by_principal" not in payload

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_silent_emits_creation_mode_silent_pickup_requested_false(self) -> None:
        """silent=True sets creation_mode=silent and pickup_requested=False in the event."""
        mock_db = self._make_content_create_mock_db()
        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes._sync_artifact_provenance_state", new_callable=AsyncMock),
            patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock) as mock_emit,
        ):
            await todo_routes.todo_content_create(
                TodoDumpRequest(slug=_MY_SLUG, content="some content", cwd=_REPO_CWD, silent=True)
            )

        payload = mock_emit.call_args.kwargs["payload"]
        assert payload["creation_mode"] == _CREATION_MODE_SILENT
        assert payload["pickup_requested"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_bug_kind_emits_canonical_kind_bug(self) -> None:
        """bug kind maps to canonical kind=bug in the emitted event."""
        mock_db = self._make_content_create_mock_db()
        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes.apply_prepared_state", return_value={"lifecycle_phase": _PREPARED}),
            patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock) as mock_emit,
        ):
            await todo_routes.todo_content_create(
                TodoDumpRequest(slug=_MY_SLUG, content="bug content", kind="bug", cwd=_REPO_CWD)
            )

        payload = mock_emit.call_args.kwargs["payload"]
        assert payload["kind"] == KIND_BUG

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_content_create_with_empty_content_does_not_emit_any_event(self) -> None:
        """Rejected whitespace-only content emits no event."""
        mock_db = MagicMock()
        mock_db.read_state = AsyncMock(return_value=None)
        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes.emit_event", new_callable=AsyncMock) as mock_emit,
            pytest.raises(HTTPException),
        ):
            await todo_routes.todo_content_create(TodoDumpRequest(slug=_MY_SLUG, content="   ", cwd=_REPO_CWD))
        mock_emit.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_reactivate_requires_clearance(self) -> None:
        """reactivate route must carry Depends(clearance_todos_reactivate)."""
        route = next(
            r
            for r in todo_routes.router.routes
            if isinstance(r, APIRoute) and r.endpoint is todo_routes.todo_reactivate
        )
        bound = {dep.call for dep in route.dependant.dependencies}
        assert clearance_todos_reactivate in bound

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_reactivate_dispatches_to_db(self) -> None:
        """POST /todos/{slug}/reactivate resolves slug and calls db.reactivate_removed."""
        mock_db = AsyncMock()
        mock_db.list_roadmap = AsyncMock(return_value=[{"id": "row-123", "slug": _TRASHED_SLUG, "status": "removed"}])
        mock_db.reactivate_removed = AsyncMock()

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            response = await todo_routes.todo_reactivate(
                slug=_TRASHED_SLUG,
                cwd=_REPO_CWD,
                _identity=_identity(),
            )

        assert response.status == _STATUS_OK
        assert response.slug == _TRASHED_SLUG
        mock_db.reactivate_removed.assert_awaited_once_with("row-123")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_reactivate_refuses_ambiguous_slug(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        """Reactivate returns 409 when multiple removed rows share the slug."""
        repo_cwd = str(tmp_path / "repo")
        Path(repo_cwd).mkdir()
        mock_db = AsyncMock()
        mock_db.list_roadmap = AsyncMock(
            return_value=[
                {"id": "row-1", "slug": "dup", "status": "removed", "removed_at": "t1"},
                {"id": "row-2", "slug": "dup", "status": "removed", "removed_at": "t2"},
            ]
        )

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_reactivate(slug="dup", cwd=repo_cwd, _identity=_identity())

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == snapshot

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_reactivate_by_id_dispatches_directly(self) -> None:
        """POST /todos/by-id/{roadmap_id}/reactivate calls db.reactivate_removed directly."""
        mock_db = AsyncMock()
        mock_db.reactivate_removed = AsyncMock(return_value=_RESTORED_SLUG)

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            response = await todo_routes.todo_reactivate_by_id(
                roadmap_id="row-123",
                cwd=_REPO_CWD,
                _identity=_identity(),
            )

        assert response.status == _STATUS_OK
        assert response.slug == _RESTORED_SLUG
        mock_db.reactivate_removed.assert_awaited_once_with("row-123")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_show_passes_include_removed_flag(self) -> None:
        """GET /todos/{slug}/show passes include_removed to assemble_show_payload."""
        mock_db = AsyncMock()
        mock_payload = {"slug": "my-slug"}

        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes.assemble_show_payload", return_value=mock_payload) as mock_assemble,
        ):
            await todo_routes.todo_show(slug="my-slug", cwd=_REPO_CWD, include_removed=True)

        mock_assemble.assert_awaited_once()
        _, kwargs = mock_assemble.call_args
        assert kwargs["include_removed"] is True
