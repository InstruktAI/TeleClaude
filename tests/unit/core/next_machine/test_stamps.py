"""Unit tests for local todo stamp application."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import CreativePhase
from teleclaude.core.next_machine.create import _derive_creative_phase
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import DependencyEntry

_STAMPS = "teleclaude.core.next_machine.stamps"
_HEAD_SHA = "origin-main-sha"
_SNIPPET_ID = "project/spec/example"
_SNIPPET_DIGEST = "snippet-digest"
_DEPENDENCY = DependencyEntry(dep_slug="dep", roadmap_status="active")


async def _make_db(tmp_path: Path) -> TodosDb:
    database = TodosDb(str(tmp_path / ".teleclaude" / "todos.db"))
    await database.initialize()
    await database.add_to_roadmap("my-slug")
    return database


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prd_approved_records_artifact_provenance_and_approval(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "prd_human_approval"})
        await database.write_artifact("my-slug", "prd", "# PRD")
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            state = await apply_todo_stamp(
                cwd=str(tmp_path),
                slug="my-slug",
                stamp_type="prd_approved",
                caller_session_id="human-session",
            )

        approvals = state["approvals"]
        assert isinstance(approvals, dict)
        prd_approved = approvals["prd_approved"]
        assert isinstance(prd_approved, dict)
        assert prd_approved["approved"] is True
        assert prd_approved["caller_session_id"] == "human-session"
        artifacts = state["artifacts"]
        assert isinstance(artifacts, dict)
        prd = artifacts["prd"]
        assert isinstance(prd, dict)
        assert prd["digest"]
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approval_rejects_missing_artifact(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "prd_human_approval"})
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            with pytest.raises(StateMutationError):
                await apply_todo_stamp(
                    cwd=str(tmp_path),
                    slug="my-slug",
                    stamp_type="prd_approved",
                    caller_session_id="human-session",
                )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_stamp_requires_reason(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "architecture_drafting"})
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            with pytest.raises(StateMutationError):
                await apply_todo_stamp(
                    cwd=str(tmp_path),
                    slug="my-slug",
                    stamp_type="architecture_skipped",
                    value="",
                )
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drift_reviewed_records_per_artifact_verdict(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "prepared"})
        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            state = await apply_todo_stamp(
                cwd=str(tmp_path),
                slug="my-slug",
                stamp_type="drift_reviewed",
                value='{"artifact": "prd", "verdict": "cosmetic", "reason": "comments only"}',
                caller_session_id="worker",
            )

        approvals = state["approvals"]
        assert isinstance(approvals, dict)
        drift = approvals["drift_reviewed"]
        assert isinstance(drift, dict)
        prd_drift = drift["prd"]
        assert isinstance(prd_drift, dict)
        assert prd_drift["verdict"] == "cosmetic"
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drift_reviewed_records_anchor_fields(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state(
            "my-slug",
            {
                "lifecycle_phase": "prepared",
                "artifacts": {
                    "architecture": {
                        "digest": "architecture-digest",
                        "async_provenance_complete": True,
                    },
                    "prd": {"digest": "prd-digest"},
                },
            },
        )
        await database.write_artifact("my-slug", "architecture", "@docs/project/spec/example.md")
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_origin_main_sha", return_value=_HEAD_SHA),
            patch(f"{_STAMPS}.read_owned_snippet_digests", new=AsyncMock(return_value={_SNIPPET_ID: _SNIPPET_DIGEST})),
            patch(
                f"{_STAMPS}.read_referenced_snippet_digests",
                new=AsyncMock(return_value={_SNIPPET_ID: _SNIPPET_DIGEST}),
            ),
            patch(f"{_STAMPS}.read_dependency_set", new=AsyncMock(return_value=[_DEPENDENCY])),
        ):
            state = await apply_todo_stamp(
                cwd=str(tmp_path),
                slug="my-slug",
                stamp_type="drift_reviewed",
                value='{"artifact": "architecture", "verdict": "cosmetic", "reason": "comments only"}',
                caller_session_id="worker",
            )

        approvals = state["approvals"]
        assert isinstance(approvals, dict)
        drift_by_artifact = approvals["drift_reviewed"]
        assert isinstance(drift_by_artifact, dict)
        drift = drift_by_artifact["architecture"]
        assert isinstance(drift, dict)
        assert drift["head_sha_at_review"] == _HEAD_SHA
        assert drift["upstream_digests_at_review"] == {"prd": "prd-digest"}
        assert drift["snippet_digests_at_review"] == {_SNIPPET_ID: _SNIPPET_DIGEST}
        assert drift["dep_set_at_review"] == [_DEPENDENCY.model_dump()]
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_substantive_drift_review_clears_downstream_review_verdicts(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state(
            "my-slug",
            {
                "lifecycle_phase": "prepared",
                "approvals": {"prd_approved": {"approved": True}},
                "artifacts": {
                    "architecture": {
                        "digest": "architecture-digest",
                        "async_provenance_complete": True,
                    },
                    "implementation_plan": {
                        "digest": "plan-digest",
                        "async_provenance_complete": True,
                    },
                },
                "architecture_review": {"verdict": "approve", "reviewed_at": "now"},
                "plan_review": {"verdict": "approve", "reviewed_at": "now"},
            },
        )
        await database.write_artifact("my-slug", "architecture", "architecture body")
        with (
            patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)),
            patch(f"{_STAMPS}.get_origin_main_sha", return_value=_HEAD_SHA),
            patch(f"{_STAMPS}.read_owned_snippet_digests", new=AsyncMock(return_value={})),
            patch(f"{_STAMPS}.read_referenced_snippet_digests", new=AsyncMock(return_value={})),
            patch(f"{_STAMPS}.read_dependency_set", new=AsyncMock(return_value=[])),
        ):
            state = await apply_todo_stamp(
                cwd=str(tmp_path),
                slug="my-slug",
                stamp_type="drift_reviewed",
                value='{"artifact": "architecture", "verdict": "substantive", "reason": "contract changed"}',
                caller_session_id="worker",
            )

        approvals = state["approvals"]
        assert isinstance(approvals, dict)
        prd_approved = approvals["prd_approved"]
        assert isinstance(prd_approved, dict)
        assert prd_approved["approved"] is True
        architecture_review = state["architecture_review"]
        assert isinstance(architecture_review, dict)
        plan_review = state["plan_review"]
        assert isinstance(plan_review, dict)
        assert architecture_review["verdict"] == ""
        assert architecture_review["cleared_by_substantive_drift"] is True
        assert plan_review["verdict"] == ""
        assert plan_review["cleared_by_substantive_drift"] is True
    finally:
        await database.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deferrals_processed_stamp_clears_pending_deferrals_route(tmp_path: Path) -> None:
    database = await _make_db(tmp_path)
    try:
        await database.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
        await database.write_artifact("my-slug", "deferrals", "- defer follow-up")
        assert await database.has_pending_deferrals("my-slug") is True

        with patch(f"{_STAMPS}.get_todos_db", new=AsyncMock(return_value=database)):
            await apply_todo_stamp(
                cwd=str(tmp_path),
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
                cwd=str(tmp_path),
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
            with pytest.raises(PermissionError):
                await apply_todo_stamp(
                    cwd=str(tmp_path),
                    slug="my-slug",
                    stamp_type="build_complete",
                    value="true",
                )
    finally:
        await database.close()
