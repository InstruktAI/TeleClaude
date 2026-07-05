"""Functional coverage for integration state machine behavior."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple, cast
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.constants import WORKTREE_DIR, TodoStatus
from teleclaude.core.blueprint import BlueprintStatus, graph_path, manifest_path, read_manifest
from teleclaude.core.db import Db
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _now_iso,
    _read_checkpoint,
    _write_checkpoint,
)
from teleclaude.core.integration.state_machine import next_integrate
from teleclaude.core.integration.step_functions import (
    _ERROR_ABANDON_RESET_FAILED,
    _ERROR_ABANDON_RETRACTION_FAILED,
    _step_push_succeeded,
)
from teleclaude.core.next_machine._types import default_state
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.hooks.checkpoint_flags import read_integrator_maintenance_marker

_SPEC = "project/spec/feature/workflow/integration-state-machine"

_FAKE_SESSION = "integrator-test-session"

_SLUG = "test-slug"

_PLANNED_BODY = "Planned content that becomes live on delivery."


def _seed_active_todo(project_root: Path, slug: str = _SLUG) -> None:
    """Insert an active todo row directly so deliver_sync can flip it to delivered.

    Pure sync sqlite (no event loop) — fast and signal-safe under the parallel
    timeout harness, where an asyncio.run seed risks crashing the xdist worker.
    """
    db = get_todos_db_sync(str(project_root))
    conn = db._sync_conn()
    now = "2026-01-01T00:00:00+00:00"
    try:
        conn.execute(
            "INSERT OR IGNORE INTO todo (id, slug, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 'active', ?, ?)",
            (f"{slug}-id", slug, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_state(
    project_root: Path,
    slug: str = _SLUG,
    *,
    finalize_status: str = "ready",
    hold: bool = False,
    cleared_by_substantive_drift: bool = False,
) -> None:
    """Write a persisted TodoState so retraction / scan-exclusion logic has state to read."""
    db = get_todos_db_sync(str(project_root))
    state = default_state()
    state["finalize"] = {
        "status": finalize_status,
        "branch": slug,
        "sha": "deadbeef",
        "ready_at": "2026-01-01T00:00:00+00:00",
        "worker_session_id": "",
    }
    state["hold"] = hold
    plan_review = dict(cast(dict, state.get("plan_review") or {}))
    plan_review["cleared_by_substantive_drift"] = cleared_by_substantive_drift
    state["plan_review"] = plan_review
    db.write_state_sync(slug, state)


def _read_state(project_root: Path, slug: str = _SLUG) -> dict | None:
    db = get_todos_db_sync(str(project_root))
    return db.read_state_sync(slug)


class _TodoRow(NamedTuple):
    status: str
    delivered_commit: str | None


def _todo_row(project_root: Path, slug: str = _SLUG) -> _TodoRow | None:
    """Read the persisted todo row (status, delivered_commit) from todos.db."""
    db = get_todos_db_sync(str(project_root))
    conn = db._sync_conn()
    try:
        cursor = conn.execute(
            "SELECT status, delivered_commit FROM todo WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _TodoRow(status=row[0], delivered_commit=row[1])


def _make_checkpoint(pre_merge_head: str | None = "abc123") -> IntegrationCheckpoint:
    now = _now_iso()
    return IntegrationCheckpoint(
        phase=IntegrationPhase.PUSH_SUCCEEDED.value,
        candidate_slug="test-slug",
        candidate_branch="test-slug",
        candidate_sha="def456",
        lease_token="lease-token",
        items_processed=0,
        items_blocked=0,
        started_at=now,
        last_updated_at=now,
        error_context=None,
        pre_merge_head=pre_merge_head,
        warnings=[],
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM1")
def test_delivery_writes_maintenance_marker_with_range_before_candidate_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delivery writes the integrator-maintenance marker with the merge range.

    The marker must survive the CANDIDATE_DELIVERED reset so the agent-stop
    checkpoint can read it.
    """
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    pre_merge_sha = "pre111aaa"
    post_merge_sha = "post999bbb"

    checkpoint_path = tmp_path / "integrate-state.json"
    cp = _make_checkpoint(pre_merge_head=pre_merge_sha)
    _write_checkpoint(checkpoint_path, cp)
    _seed_active_todo(tmp_path)

    with (
        patch("teleclaude.core.integration.step_functions.get_session_id", return_value=_FAKE_SESSION),
        patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
        patch("teleclaude.core.integration.git_ops._run_git", new=mock_git),
        patch("teleclaude.core.integration.step_functions._get_head_sha", return_value=post_merge_sha),
        patch("teleclaude.core.integration.step_functions._do_cleanup") as mock_cleanup,
        patch("teleclaude.core.integration.step_functions._regenerate_blueprint_after_delivery", return_value=None),
    ):
        # Simulate pull succeeding, no bookkeeping commits ahead
        def _fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
            if args[:2] == ["pull", "--ff-only"]:
                return 0, "", ""
            if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
                return 0, "0\n", ""
            return 0, "", ""

        mock_git.side_effect = _fake_run_git
        mock_cleanup.return_value = (True, "")

        _step_push_succeeded(
            checkpoint=cp,
            checkpoint_path=checkpoint_path,
            cwd=str(tmp_path),
        )

    marker_content = read_integrator_maintenance_marker(_FAKE_SESSION)
    assert marker_content is not None
    expected_range = f"{pre_merge_sha}..{post_merge_sha}"
    marker_lines = [line for line in marker_content.strip().splitlines() if line]
    assert expected_range in marker_lines


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM1")
def test_maintenance_marker_accumulates_across_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple deliveries accumulate ranges in the marker file."""
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "flags"))

    ranges = [("pre1", "post1"), ("pre2", "post2")]
    checkpoint_path = tmp_path / "integrate-state.json"
    _seed_active_todo(tmp_path)

    for pre_sha, post_sha in ranges:
        cp = _make_checkpoint(pre_merge_head=pre_sha)
        _write_checkpoint(checkpoint_path, cp)

        with (
            patch("teleclaude.core.integration.step_functions.get_session_id", return_value=_FAKE_SESSION),
            patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
            patch("teleclaude.core.integration.git_ops._run_git", new=mock_git),
            patch("teleclaude.core.integration.step_functions._get_head_sha", return_value=post_sha),
            patch("teleclaude.core.integration.step_functions._do_cleanup") as mock_cleanup,
            patch("teleclaude.core.integration.step_functions._regenerate_blueprint_after_delivery", return_value=None),
        ):

            def _fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
                if args[:2] == ["pull", "--ff-only"]:
                    return 0, "", ""
                if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
                    return 0, "0\n", ""
                return 0, "", ""

            mock_git.side_effect = _fake_run_git
            mock_cleanup.return_value = (True, "")

            _step_push_succeeded(
                checkpoint=cp,
                checkpoint_path=checkpoint_path,
                cwd=str(tmp_path),
            )

    marker_content = read_integrator_maintenance_marker(_FAKE_SESSION)
    assert marker_content is not None
    # Verify both ranges accumulated using variable identity (no string literal on left side of `in`)
    range_1 = f"{ranges[0][0]}..{ranges[0][1]}"
    range_2 = f"{ranges[1][0]}..{ranges[1][1]}"
    marker_lines = [line for line in marker_content.strip().splitlines() if line]
    assert range_1 in marker_lines
    assert range_2 in marker_lines


def _patch_step_push_git(mock_git: MagicMock) -> None:
    """Drive _step_push_succeeded down the pull-succeeded, no-bookkeeping path."""

    def _fake_run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args[:2] == ["pull", "--ff-only"]:
            return 0, "", ""
        if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
            return 0, "0\n", ""
        return 0, "", ""

    mock_git.side_effect = _fake_run_git


@pytest.mark.functional
def test_delivery_regenerates_blueprint_with_pushed_baseline(tmp_path: Path) -> None:
    """A successful delivery writes the Blueprint graph + manifest at the pushed baseline."""
    post_merge_sha = "blueprintbaseline0001"
    checkpoint_path = tmp_path / "integrate-state.json"
    cp = _make_checkpoint()
    _write_checkpoint(checkpoint_path, cp)
    _seed_active_todo(tmp_path)

    def _fake_graphify_update(repo_root: Path) -> int:
        out = Path(repo_root) / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "graph.json").write_text('{"nodes": [], "links": []}')
        return 0

    with (
        patch("teleclaude.core.integration.step_functions.get_session_id", return_value=None),
        patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
        patch("teleclaude.core.integration.git_ops._run_git", new=mock_git),
        patch("teleclaude.core.integration.step_functions._get_head_sha", return_value=post_merge_sha),
        patch("teleclaude.core.integration.step_functions._do_cleanup", return_value=(True, "")),
        patch("teleclaude.core.blueprint.generate._run_graphify_update", side_effect=_fake_graphify_update),
    ):
        _patch_step_push_git(mock_git)
        success, _ = _step_push_succeeded(checkpoint=cp, checkpoint_path=checkpoint_path, cwd=str(tmp_path))

    assert success is True
    assert graph_path(tmp_path).is_file()
    manifest = read_manifest(manifest_path(tmp_path))
    assert manifest is not None
    assert manifest.status is BlueprintStatus.OK
    assert manifest.baseline_sha == post_merge_sha


@pytest.mark.functional
def test_delivery_completes_when_blueprint_regeneration_fails(tmp_path: Path) -> None:
    """A graphify failure records a non-ok manifest and never blocks the integration."""
    checkpoint_path = tmp_path / "integrate-state.json"
    cp = _make_checkpoint()
    _write_checkpoint(checkpoint_path, cp)
    _seed_active_todo(tmp_path)

    with (
        patch("teleclaude.core.integration.step_functions.get_session_id", return_value=None),
        patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
        patch("teleclaude.core.integration.git_ops._run_git", new=mock_git),
        patch("teleclaude.core.integration.step_functions._get_head_sha", return_value="failsha0002"),
        patch("teleclaude.core.integration.step_functions._do_cleanup", return_value=(True, "")),
        patch("teleclaude.core.blueprint.generate._run_graphify_update", return_value=1),
    ):
        _patch_step_push_git(mock_git)
        success, _ = _step_push_succeeded(checkpoint=cp, checkpoint_path=checkpoint_path, cwd=str(tmp_path))

    assert success is True
    assert not graph_path(tmp_path).is_file()
    manifest = read_manifest(manifest_path(tmp_path))
    assert manifest is not None
    assert manifest.status is BlueprintStatus.ERROR


@pytest.mark.functional
def test_delivery_warns_when_blueprint_manifest_write_fails(tmp_path: Path, snapshot: object) -> None:
    """A manifest write failure is surfaced as a warning instead of a false ok result."""
    checkpoint_path = tmp_path / "integrate-state.json"
    cp = _make_checkpoint()
    _write_checkpoint(checkpoint_path, cp)
    _seed_active_todo(tmp_path)

    def _fake_graphify_update(repo_root: Path) -> int:
        out = Path(repo_root) / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "graph.json").write_text('{"nodes": [], "links": []}')
        return 0

    with (
        patch("teleclaude.core.integration.step_functions.get_session_id", return_value=None),
        patch("teleclaude.core.integration.step_functions._run_git") as mock_git,
        patch("teleclaude.core.integration.git_ops._run_git", new=mock_git),
        patch("teleclaude.core.integration.step_functions._get_head_sha", return_value="manifestfailsha0003"),
        patch("teleclaude.core.integration.step_functions._do_cleanup", return_value=(True, "")),
        patch("teleclaude.core.blueprint.generate._run_graphify_update", side_effect=_fake_graphify_update),
        patch("teleclaude.core.blueprint.generate.write_manifest", side_effect=OSError("disk full")),
    ):
        _patch_step_push_git(mock_git)
        success, _ = _step_push_succeeded(checkpoint=cp, checkpoint_path=checkpoint_path, cwd=str(tmp_path))

    assert success is True
    assert graph_path(tmp_path).is_file()
    assert "\n".join(cp.warnings) == snapshot


# ---------------------------------------------------------------------------
# UC-WISM2: delivery recorded only on a confirmed push
# ---------------------------------------------------------------------------


def _make_fake_git(
    *,
    push_rc: int = 0,
    push_stderr: str = "! [rejected] (non-fast-forward)",
    content_contained: bool = True,
    fetch_rc: int = 0,
    reset_rc: int = 0,
    probe_cleanup_reset_rc: int = 0,
    add_rc: int = 0,
    commit_rc: int = 0,
    staged_dirty: bool = False,
) -> Callable[..., tuple[int, str, str]]:
    """Script the process-boundary git calls for a driven integration.

    Only the push result, the confirmation re-fetch, the post-push containment
    probe, the post-push reset, and (for the fold-carrying delivery path) the
    ``add`` / ``commit`` results and the staged-diff probe vary per scenario;
    every other git call is a benign success so the dispatcher and steps flow to
    the gate.

    The containment probe (``git merge --squash <candidate-sha>`` followed by
    ``git diff --cached --quiet``) shares the ``diff --cached --quiet`` command
    shape with the delivery-bookkeeping fold-staging check, so a probe-pending
    flag distinguishes the probe's diff call (governed by ``content_contained``)
    from the fold's diff call (governed by ``staged_dirty``). ``probe_cleanup_reset_rc``
    governs the probe's own cleanup ``reset --hard HEAD`` (distinct from the
    pre-probe ``reset --hard origin/main`` governed by ``reset_rc``).
    """
    probe_pending = {"value": False}

    def _fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args[:2] == ["push", "origin"]:
            return push_rc, "", (push_stderr if push_rc != 0 else "")
        if args[:2] == ["fetch", "origin"]:
            return fetch_rc, "", ("fatal: unable to access origin" if fetch_rc != 0 else "")
        if args[:3] == ["reset", "--hard", "origin/main"]:
            return reset_rc, "", ""
        if args[:3] == ["reset", "--hard", "HEAD"]:
            return probe_cleanup_reset_rc, "", ("fatal: cleanup reset failed" if probe_cleanup_reset_rc != 0 else "")
        if args[:2] == ["merge", "--squash"]:
            probe_pending["value"] = True
            return 0, "", ""
        if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
            return 0, "0\n", ""
        if args[:1] == ["add"]:
            return add_rc, "", ("fatal: unable to stage" if add_rc != 0 else "")
        if args[:3] == ["diff", "--cached", "--quiet"]:
            if probe_pending["value"]:
                probe_pending["value"] = False
                return (0 if content_contained else 1), "", ""
            return (1 if staged_dirty else 0), "", ""
        if args[:1] == ["commit"]:
            return commit_rc, "", ("fatal: commit failed" if commit_rc != 0 else "")
        return 0, "", ""

    return _fake_git


def _integration_docs_root(tmp_path: Path) -> Path:
    """Docs tree the delivered-snippet fold scans inside the integration worktree."""
    return tmp_path / WORKTREE_DIR / "_integration" / "docs" / "project"


async def _drive_integrate(
    *,
    tmp_path: Path,
    seed_phase: IntegrationPhase,
    landed_sha: str,
    fake_git: Callable[..., tuple[int, str, str]],
    remote_main_sha: str | None = None,
    seed_snippets: dict[str, str] | None = None,
    reconcile_side_effect: BaseException | None = None,
) -> tuple[str, IntegrationPhase]:
    """Seed a durable checkpoint and a real active todo row, then drive next_integrate.

    Returns the agent instruction and the persisted checkpoint phase. Fakes only
    the process boundary (git, the bus emission, the graphify subprocess) and the
    external store locations (checkpoint dir, todos.db) — every in-process step
    runs for real.

    ``seed_snippets`` writes real Markdown files (relative to the integration
    worktree's ``docs/project`` root) so the real delivered-snippet fold has a
    tree to reconcile. ``reconcile_side_effect`` injects a process-boundary
    failure (e.g. ``OSError``) into the fold without faking its result.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    checkpoint_path = state_dir / "integrate-state.json"
    cp = _make_checkpoint()
    cp.phase = seed_phase.value
    if seed_phase == IntegrationPhase.PUSH_REJECTED:
        cp.error_context = {"rejection_reason": "non-fast-forward"}
    _write_checkpoint(checkpoint_path, cp)
    _seed_active_todo(tmp_path)

    if seed_snippets:
        docs_root = _integration_docs_root(tmp_path)
        for rel_path, content in seed_snippets.items():
            snippet_path = docs_root / rel_path
            snippet_path.parent.mkdir(parents=True, exist_ok=True)
            snippet_path.write_text(content, encoding="utf-8")

    sf = "teleclaude.core.integration.step_functions"
    sm = "teleclaude.core.integration.state_machine"
    with ExitStack() as stack:
        stack.enter_context(patch(f"{sm}._default_state_dir", return_value=state_dir))
        stack.enter_context(patch(f"{sm}._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{sf}._run_git", side_effect=fake_git))
        stack.enter_context(patch("teleclaude.core.integration.git_ops._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{sf}._get_head_sha", return_value=landed_sha))
        stack.enter_context(
            patch(
                f"{sf}._get_remote_main_sha",
                return_value=remote_main_sha if remote_main_sha is not None else landed_sha,
            )
        )
        stack.enter_context(patch(f"{sf}._regenerate_blueprint_after_delivery", return_value=None))
        stack.enter_context(patch(f"{sf}._emit_lifecycle_event"))
        stack.enter_context(patch(f"{sf}.cleanup_delivered_slug"))
        stack.enter_context(patch(f"{sf}.get_session_id", return_value=None))
        if reconcile_side_effect is not None:
            stack.enter_context(
                patch(
                    "teleclaude.core.integration.delivery_fold.reconcile_delivered_snippets",
                    side_effect=reconcile_side_effect,
                )
            )
        instruction = await next_integrate(cast(Db, MagicMock()), _SLUG, str(tmp_path))

    persisted_phase = IntegrationPhase(_read_checkpoint(checkpoint_path).phase)
    return instruction, persisted_phase


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_rejected_push_leaves_todo_not_delivered(tmp_path: Path) -> None:
    """A rejected push records no delivery and leaves the phase at PUSH_REJECTED."""
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="squashhead0001",
        fake_git=_make_fake_git(push_rc=1),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_confirmed_push_delivers_once_with_landed_commit(tmp_path: Path) -> None:
    """A confirmed push delivers exactly once, recording the worktree HEAD on main."""
    landed_sha = "squashhead0002"
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha=landed_sha,
        fake_git=_make_fake_git(push_rc=0, content_contained=True),
    )

    assert phase is not IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status == TodoStatus.DELIVERED
    assert row.delivered_commit == landed_sha


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_recovered_push_delivers_once_with_landed_commit(tmp_path: Path) -> None:
    """Operator recovery (worktree HEAD == origin/main) delivers exactly once."""
    landed_sha = "recoveredhead0003"
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.PUSH_REJECTED,
        landed_sha=landed_sha,
        fake_git=_make_fake_git(content_contained=True),
        remote_main_sha=landed_sha,
    )

    assert phase is not IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status == TodoStatus.DELIVERED
    assert row.delivered_commit == landed_sha


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_push_success_but_content_not_contained_withholds_delivery(tmp_path: Path) -> None:
    """A push that reports success but the candidate's content is absent from main withholds delivery.

    Proves the gate checks candidate-content containment, not merely that the
    worktree HEAD moved — a reset-to-origin/main-and-drop-the-squash scenario
    would otherwise slip through and false-deliver.
    """
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="orphanhead0004",
        fake_git=_make_fake_git(push_rc=0, content_contained=False),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_reset_to_origin_main_with_dropped_squash_withholds_delivery(tmp_path: Path) -> None:
    """Resetting the integration worktree to origin/main (dropping the squash) never false-delivers.

    The fast pre_merge_head guard catches the common case: nothing else landed on
    main, so the reset lands the worktree HEAD back on the exact pre-merge SHA
    (``_make_checkpoint``'s default ``pre_merge_head``, "abc123").
    """
    pre_merge_sha = "abc123"
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.PUSH_REJECTED,
        landed_sha=pre_merge_sha,
        fake_git=_make_fake_git(content_contained=True),
        remote_main_sha=pre_merge_sha,
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_branch_moved_to_unrelated_content_withholds_delivery(tmp_path: Path) -> None:
    """The containment probe grounds on the frozen candidate SHA, not the branch tip.

    If the candidate's branch moved to unrelated content after finalize while the
    candidate's own commit content is absent from main, delivery must still be
    withheld — proving the probe reads ``key.sha``, never ``key.branch``.
    """
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="branchmoved0013",
        fake_git=_make_fake_git(push_rc=0, content_contained=False),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_containment_probe_cleanup_failure_withholds_delivery(tmp_path: Path) -> None:
    """A cleanup failure after an otherwise-successful containment probe still withholds delivery.

    The merge succeeds and the staged diff is empty (would-be `contained=True`),
    but the probe's own cleanup (`reset --hard HEAD`) fails. Delivery must be
    withheld regardless — a cleanup failure means the worktree state the probe
    ran against can no longer be trusted clean.
    """
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="cleanupfail0019",
        fake_git=_make_fake_git(push_rc=0, content_contained=True, probe_cleanup_reset_rc=1),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_fetch_failure_withholds_delivery(tmp_path: Path) -> None:
    """A failed confirmation re-fetch withholds delivery (no trusting a stale ref)."""
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="staleref0006",
        fake_git=_make_fake_git(push_rc=0, content_contained=True, fetch_rc=1),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_push_rejection_recovery_instruction_is_worktree_qualified(tmp_path: Path, snapshot: object) -> None:
    """The recovery instruction directory-qualifies each git command to the worktree.

    ``_step_push_rejected`` now re-attempts the push itself on re-entry (to
    observe a fresh rejection cause); ``push_rc=1`` keeps this still-unrecovered
    so the rebase-recovery instruction is what's rendered.
    """
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.PUSH_REJECTED,
        landed_sha="localhead0005",
        fake_git=_make_fake_git(push_rc=1),
        remote_main_sha="remotehead9999",
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    worktree = str((tmp_path / "trees" / "_integration").resolve())
    normalized = instruction.replace(worktree, "<INTEGRATION_WORKTREE>")
    assert normalized == snapshot


# ---------------------------------------------------------------------------
# UC-WISM3 / UC-WISM4 — delivery-chokepoint fold + fail-closed pre-push gate
# ---------------------------------------------------------------------------


def _recording_fake_git(records: list[list[str]], **kwargs: object) -> Callable[..., tuple[int, str, str]]:
    """A scripted fake git that also records every command it sees."""
    base = _make_fake_git(**cast(dict, kwargs))

    def _fake(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        records.append(list(args))
        return base(args, cwd=cwd, timeout=timeout)

    return _fake


def _pushed(records: list[list[str]]) -> bool:
    return any(args[:2] == ["push", "origin"] for args in records)


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM3")
async def test_delivery_bookkeeping_folds_planned_marker_on_committed_path(tmp_path: Path) -> None:
    """A committed (non-eager-fold) delivery folds the slug's planned markers before push.

    Seeding at COMMITTED means the clean-merge eager fold in ``_do_merge`` never
    ran, so a surviving marker can only be folded by the delivery-bookkeeping
    chokepoint. The real reconcile runs over a real docs tree; only git is faked.
    """
    snippet = (
        "# Sample Snippet\n\n"
        "A live paragraph.\n\n"
        f"<!-- planned:{_SLUG} -->\n"
        f"{_PLANNED_BODY}\n"
        f"<!-- /planned:{_SLUG} -->\n"
    )
    landed_sha = "foldedhead0007"
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.COMMITTED,
        landed_sha=landed_sha,
        fake_git=_make_fake_git(push_rc=0, content_contained=True),
        seed_snippets={"spec/sample.md": snippet},
    )

    folded = (_integration_docs_root(tmp_path) / "spec" / "sample.md").read_text(encoding="utf-8")
    assert f"planned:{_SLUG}" not in folded
    assert _PLANNED_BODY in folded

    assert phase is not IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status == TodoStatus.DELIVERED
    assert row.delivered_commit == landed_sha


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM4")
async def test_residual_marker_fails_closed_before_push(tmp_path: Path) -> None:
    """A marker the fold cannot resolve keeps the candidate at the gate and suppresses the push."""
    snippet = (
        "# Sample Snippet\n\n"
        "A live paragraph.\n\n"
        f"<!-- planned-change:{_SLUG} -->\n"
        "An unresolved planned-change marker the fold cannot close.\n"
    )
    records: list[list[str]] = []
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="blockedhead0008",
        fake_git=_recording_fake_git(records, push_rc=0, content_contained=True),
        seed_snippets={"spec/sample.md": snippet},
    )

    assert phase is IntegrationPhase.DELIVERY_BOOKKEEPING
    assert not _pushed(records)
    assert _SLUG in instruction
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


def _planned_snippet() -> str:
    return (
        "# Sample Snippet\n\n"
        "A live paragraph.\n\n"
        f"<!-- planned:{_SLUG} -->\n"
        f"{_PLANNED_BODY}\n"
        f"<!-- /planned:{_SLUG} -->\n"
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM3")
async def test_fold_staging_failure_fails_closed_before_push(tmp_path: Path) -> None:
    """If staging the fold fails, the unstaged fold never reaches the commit — fail closed."""
    records: list[list[str]] = []
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.COMMITTED,
        landed_sha="addfail0010",
        fake_git=_recording_fake_git(records, push_rc=0, content_contained=True, add_rc=1),
        seed_snippets={"spec/sample.md": _planned_snippet()},
    )

    assert phase is IntegrationPhase.DELIVERY_BOOKKEEPING
    assert not _pushed(records)
    assert _SLUG in instruction
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM3")
async def test_cleanup_commit_failure_fails_closed_before_push(tmp_path: Path) -> None:
    """If the commit carrying the staged fold fails, the fold is uncommitted — fail closed."""
    records: list[list[str]] = []
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.COMMITTED,
        landed_sha="commitfail0011",
        fake_git=_recording_fake_git(records, push_rc=0, content_contained=True, staged_dirty=True, commit_rc=1),
        seed_snippets={"spec/sample.md": _planned_snippet()},
    )

    assert phase is IntegrationPhase.DELIVERY_BOOKKEEPING
    assert not _pushed(records)
    assert _SLUG in instruction
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM4")
async def test_fold_oserror_fails_closed_before_push(tmp_path: Path) -> None:
    """A fold that raises OSError at the chokepoint fails closed — the tree never reaches main."""
    records: list[list[str]] = []
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="blockedhead0009",
        fake_git=_recording_fake_git(records, push_rc=0, content_contained=True),
        reconcile_side_effect=OSError("simulated reconcile filesystem failure"),
    )

    assert phase is IntegrationPhase.DELIVERY_BOOKKEEPING
    assert not _pushed(records)
    assert _SLUG in instruction
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


# ---------------------------------------------------------------------------
# UC-WISM5: content-gate rejection abandons the candidate without freezing the queue
# ---------------------------------------------------------------------------

_CONTENT_GATE_STDERR = "ERROR: Integration push blocked — telec code lint --all failed."
_FINALIZE_STATUS_READY = "ready"
_FINALIZE_STATUS_PENDING = "pending"


def _finalize_status(project_root: Path, slug: str = _SLUG) -> str | None:
    state = _read_state(project_root, slug)
    if state is None:
        return None
    return cast(dict, state["finalize"]).get("status")


_OTHER_READY_SLUG = "other-ready-slug"
_CONFLICTED_FILE = "conflicted-file.py"


def _conflicting_dequeue_fake_git(
    records: list[list[str]], *, dequeue_branch: str
) -> Callable[..., tuple[int, str, str]]:
    """Fake the full git surface for driving `next_integrate` from IDLE onward.

    Handles the dispatcher's entry checks (pull/stash), the scan/verify
    readiness probes (ls-remote/merge-base), and — for the one candidate whose
    branch is ``dequeue_branch`` — a conflicted squash merge, so `_do_merge`
    reaches a terminal MERGE_CONFLICTED decision instead of needing a full
    commit/push/deliver flow faked out. Every call is recorded for assertion.
    """

    def _fake(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        records.append(list(args))
        if args[:2] == ["pull", "--ff-only"]:
            return 0, "", ""
        if args[:1] == ["stash"]:
            return 0, "", ""
        if args[:2] == ["push", "origin"]:
            return 1, "", _CONTENT_GATE_STDERR
        if args[:2] == ["ls-remote", "--exit-code"]:
            return 0, "", ""
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return 1, "", ""
        if args[:2] == ["merge", "--squash"] and len(args) > 2 and args[2] == dequeue_branch:
            return 1, "", ""
        if args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
            return 0, f"{_CONFLICTED_FILE}\n", ""
        return 0, "", ""

    return _fake


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM5")
async def test_content_gate_rejection_abandons_candidate_without_freezing_queue(tmp_path: Path) -> None:
    """A content-gate push rejection resets the worktree, retracts and blocks the
    candidate with the correct event payload, and keeps draining the queue —
    proven by dequeuing a second, genuinely different ready candidate in the
    same call rather than re-processing the abandoned one.
    """
    _seed_active_todo(tmp_path)
    _seed_state(tmp_path, finalize_status=_FINALIZE_STATUS_READY)

    (tmp_path / WORKTREE_DIR / _OTHER_READY_SLUG).mkdir(parents=True)
    _seed_active_todo(tmp_path, slug=_OTHER_READY_SLUG)
    _seed_state(tmp_path, slug=_OTHER_READY_SLUG, finalize_status=_FINALIZE_STATUS_READY)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    checkpoint_path = state_dir / "integrate-state.json"
    cp = _make_checkpoint()
    cp.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value
    _write_checkpoint(checkpoint_path, cp)

    records: list[list[str]] = []
    blocked_events: list[dict[str, object]] = []  # guard: loose-dict - mirrors _emit_lifecycle_event's payload shape

    # guard: loose-dict-func - payload shape varies per event type, mirrors _emit_lifecycle_event
    def _capture_emit(event_type: str, payload: dict[str, object]) -> None:
        if event_type == "integration.candidate.blocked":
            blocked_events.append(dict(payload))

    sf = "teleclaude.core.integration.step_functions"
    sm = "teleclaude.core.integration.state_machine"
    cs = "teleclaude.core.integration.candidate_scan"
    with ExitStack() as stack:
        fake_git = _conflicting_dequeue_fake_git(records, dequeue_branch=_OTHER_READY_SLUG)
        stack.enter_context(patch(f"{sm}._default_state_dir", return_value=state_dir))
        stack.enter_context(patch(f"{sm}._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{sf}._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{cs}._run_git", side_effect=fake_git))
        stack.enter_context(patch("teleclaude.core.integration.git_ops._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{sf}._emit_lifecycle_event", side_effect=_capture_emit))
        stack.enter_context(patch(f"{sf}.get_session_id", return_value=None))

        await next_integrate(cast(Db, MagicMock()), None, str(tmp_path))

    # The bad squash was actually dropped: the abandon step's own fetch + hard
    # reset ran between the rejected push and the start of the next scan (the
    # first ls-remote call) — not merely as a side effect of dequeuing the next
    # candidate's worktree sync, which happens strictly after the scan starts.
    push_idx = records.index(["push", "origin", "HEAD:main"])
    scan_idx = next(i for i, r in enumerate(records) if r[:2] == ["ls-remote", "--exit-code"])
    abandon_slice = records[push_idx:scan_idx]
    assert ["fetch", "origin"] in abandon_slice
    assert ["reset", "--hard", "origin/main"] in abandon_slice

    assert len(blocked_events) == 1
    assert blocked_events[0]["slug"] == _SLUG
    assert blocked_events[0]["branch"] == _SLUG
    assert blocked_events[0]["sha"] == cp.candidate_sha
    assert blocked_events[0]["reason"] == _CONTENT_GATE_STDERR

    persisted = _read_checkpoint(checkpoint_path)
    assert persisted.items_blocked == 1
    # The queue kept draining: a second, genuinely different candidate was
    # dequeued and reached real merge processing — not stuck on the abandoned one.
    assert persisted.candidate_slug == _OTHER_READY_SLUG
    assert persisted.phase == IntegrationPhase.MERGE_CONFLICTED.value

    assert _finalize_status(tmp_path) == _FINALIZE_STATUS_PENDING
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM5")
async def test_abandon_fails_closed_when_worktree_reset_fails(tmp_path: Path) -> None:
    """A failed worktree reset during abandon fails closed: no IDLE convergence, no blocked increment.

    Retraction (finalize.status) is committed first and stays committed — the
    fail-closed ordering means re-entry retries only the reset, never re-runs a
    retraction that already succeeded.
    """
    _seed_active_todo(tmp_path)
    _seed_state(tmp_path, finalize_status=_FINALIZE_STATUS_READY)

    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="contentgatehead0018",
        fake_git=_make_fake_git(push_rc=1, push_stderr=_CONTENT_GATE_STDERR, reset_rc=1),
    )

    assert phase is IntegrationPhase.CANDIDATE_ABANDONED
    assert _ERROR_ABANDON_RESET_FAILED in instruction
    assert _finalize_status(tmp_path) == _FINALIZE_STATUS_PENDING
    persisted = _read_checkpoint(tmp_path / "state" / "integrate-state.json")
    assert persisted.items_blocked == 0


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM5")
async def test_fast_forward_rejection_is_not_abandoned(tmp_path: Path) -> None:
    """A genuine fast-forward-race rejection is unaffected — it still parks at PUSH_REJECTED."""
    _seed_active_todo(tmp_path)
    _seed_state(tmp_path, finalize_status=_FINALIZE_STATUS_READY)

    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="raceheadr0017",
        fake_git=_make_fake_git(push_rc=1),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    assert _finalize_status(tmp_path) == _FINALIZE_STATUS_READY


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM5")
async def test_abandon_retraction_failure_fails_closed_when_state_missing(tmp_path: Path) -> None:
    """Retraction fails closed when no persisted state exists: no IDLE convergence, no blocked increment."""
    # No _seed_state call — read_state_sync finds no persisted TodoState for the slug.
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="contentgatehead0015",
        fake_git=_make_fake_git(push_rc=1, push_stderr=_CONTENT_GATE_STDERR),
    )

    assert phase is IntegrationPhase.CANDIDATE_ABANDONED
    assert _ERROR_ABANDON_RETRACTION_FAILED in instruction
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM5")
async def test_abandon_retraction_failure_fails_closed_on_write_error(tmp_path: Path) -> None:
    """A state-write failure during retraction fails closed: no IDLE convergence, state unchanged."""
    _seed_active_todo(tmp_path)
    _seed_state(tmp_path, finalize_status=_FINALIZE_STATUS_READY)

    with patch(
        "teleclaude.core.todos_db._state.TodosDbStateMixin.write_state_sync",
        side_effect=RuntimeError("simulated disk failure"),
    ):
        instruction, phase = await _drive_integrate(
            tmp_path=tmp_path,
            seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
            landed_sha="contentgatehead0016",
            fake_git=_make_fake_git(push_rc=1, push_stderr=_CONTENT_GATE_STDERR),
        )

    assert phase is IntegrationPhase.CANDIDATE_ABANDONED
    assert _ERROR_ABANDON_RETRACTION_FAILED in instruction
    # Retraction never committed.
    assert _finalize_status(tmp_path) == _FINALIZE_STATUS_READY


# ---------------------------------------------------------------------------
# UC-WISM6: held or kicked-back candidates are excluded from the integration pool
# ---------------------------------------------------------------------------


def _seed_ready_worktree(tmp_path: Path, slug: str, **state_overrides: object) -> None:
    """Seed a worktree directory plus its active todo row and finalize-ready state."""
    (tmp_path / WORKTREE_DIR / slug).mkdir(parents=True)
    _seed_active_todo(tmp_path, slug=slug)
    _seed_state(tmp_path, slug=slug, finalize_status=_FINALIZE_STATUS_READY, **cast(dict, state_overrides))


_PLAIN_READY_SLUG = "plain-ready-slug"
_HELD_SLUG = "held-slug"
_KICKED_BACK_SLUG = "kicked-back-slug"
_EXCLUDED_SLUG = "excluded-slug"


async def _drive_from_idle(
    *, tmp_path: Path, slug: str | None, fake_git: Callable[..., tuple[int, str, str]]
) -> IntegrationCheckpoint:
    """Drive a fresh, real `next_integrate` call from a clean IDLE checkpoint.

    No checkpoint file is pre-seeded — `_read_checkpoint` returns the default
    fresh-IDLE checkpoint when the path doesn't exist, and `_dispatch_sync`
    normalizes session-scoped counters on IDLE entry. Only the git subprocess
    boundary is faked; the dispatcher, `_step_idle`, the scan/verify, lease
    acquisition, and checkpoint persistence all run for real.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    checkpoint_path = state_dir / "integrate-state.json"

    sf = "teleclaude.core.integration.step_functions"
    sm = "teleclaude.core.integration.state_machine"
    cs = "teleclaude.core.integration.candidate_scan"
    with ExitStack() as stack:
        stack.enter_context(patch(f"{sm}._default_state_dir", return_value=state_dir))
        stack.enter_context(patch(f"{sm}._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{sf}._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{cs}._run_git", side_effect=fake_git))
        stack.enter_context(patch("teleclaude.core.integration.git_ops._run_git", side_effect=fake_git))
        stack.enter_context(patch(f"{sf}.get_session_id", return_value=None))

        await next_integrate(cast(Db, MagicMock()), slug, str(tmp_path))

    return _read_checkpoint(checkpoint_path)


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM6")
async def test_scan_excludes_held_and_kicked_back_candidates(tmp_path: Path) -> None:
    """The FIFO scan (driven through the public next_integrate surface) skips
    held / kicked-back candidates despite finalize.status == 'ready'."""
    _seed_ready_worktree(tmp_path, _PLAIN_READY_SLUG)
    _seed_ready_worktree(tmp_path, _HELD_SLUG, hold=True)
    _seed_ready_worktree(tmp_path, _KICKED_BACK_SLUG, cleared_by_substantive_drift=True)

    records: list[list[str]] = []
    persisted = await _drive_from_idle(
        tmp_path=tmp_path,
        slug=None,
        fake_git=_conflicting_dequeue_fake_git(records, dequeue_branch=_PLAIN_READY_SLUG),
    )

    # Only the plain-ready candidate was ever dequeued: it reached real merge
    # processing (conflict), while the held/kicked-back slugs were never
    # squash-merged at all.
    assert persisted.candidate_slug == _PLAIN_READY_SLUG
    assert persisted.phase == IntegrationPhase.MERGE_CONFLICTED.value
    assert not any(
        args[:2] == ["merge", "--squash"] and len(args) > 2 and args[2] in (_HELD_SLUG, _KICKED_BACK_SLUG)
        for args in records
    )


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM6")
@pytest.mark.parametrize(
    "state_overrides",
    [{"hold": True}, {"cleared_by_substantive_drift": True}],
    ids=["held", "kicked_back"],
)
async def test_verify_slug_excludes_held_and_kicked_back_candidate(
    tmp_path: Path, state_overrides: dict[str, bool]
) -> None:
    """An explicit-slug next_integrate call excludes a held/kicked-back candidate."""
    _seed_ready_worktree(tmp_path, _EXCLUDED_SLUG, **state_overrides)

    records: list[list[str]] = []
    persisted = await _drive_from_idle(
        tmp_path=tmp_path,
        slug=_EXCLUDED_SLUG,
        fake_git=_conflicting_dequeue_fake_git(records, dequeue_branch=_EXCLUDED_SLUG),
    )

    # No candidate dequeued and the checkpoint is left untouched — the held/
    # kicked-back slug never became eligible for integration, and its branch
    # was never even squash-merged.
    assert persisted.candidate_slug is None
    assert persisted.phase == IntegrationPhase.IDLE.value
    assert persisted.items_processed == 0
    assert not any(args[:2] == ["merge", "--squash"] for args in records)
