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
from teleclaude.core.integration.step_functions import _step_push_succeeded
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
            "INSERT INTO todo (id, slug, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 'active', ?, ?)",
            (f"{slug}-id", slug, now, now),
        )
        conn.commit()
    finally:
        conn.close()


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
    is_ancestor: bool = True,
    fetch_rc: int = 0,
    add_rc: int = 0,
    commit_rc: int = 0,
    staged_dirty: bool = False,
) -> Callable[..., tuple[int, str, str]]:
    """Script the process-boundary git calls for a driven integration.

    Only the push result, the confirmation re-fetch, the post-push ancestry check,
    and (for the fold-carrying delivery path) the ``add`` / ``commit`` results and
    the staged-diff probe vary per scenario; every other git call is a benign
    success so the dispatcher and steps flow to the gate.
    """

    def _fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args[:2] == ["push", "origin"]:
            return push_rc, "", ("! [rejected] (non-fast-forward)" if push_rc != 0 else "")
        if args[:2] == ["fetch", "origin"]:
            return fetch_rc, "", ("fatal: unable to access origin" if fetch_rc != 0 else "")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return (0 if is_ancestor else 1), "", ""
        if args[:3] == ["rev-list", "--count", "origin/main..HEAD"]:
            return 0, "0\n", ""
        if args[:1] == ["add"]:
            return add_rc, "", ("fatal: unable to stage" if add_rc != 0 else "")
        if args[:3] == ["diff", "--cached", "--quiet"]:
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
        fake_git=_make_fake_git(push_rc=0, is_ancestor=True),
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
        fake_git=_make_fake_git(is_ancestor=True),
        remote_main_sha=landed_sha,
    )

    assert phase is not IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status == TodoStatus.DELIVERED
    assert row.delivered_commit == landed_sha


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_push_success_but_not_ancestor_withholds_delivery(tmp_path: Path) -> None:
    """A push that reports success but is not an ancestor of main withholds delivery."""
    _, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.DELIVERY_BOOKKEEPING,
        landed_sha="orphanhead0004",
        fake_git=_make_fake_git(push_rc=0, is_ancestor=False),
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
        fake_git=_make_fake_git(push_rc=0, is_ancestor=True, fetch_rc=1),
    )

    assert phase is IntegrationPhase.PUSH_REJECTED
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-WISM2")
async def test_push_rejection_recovery_instruction_is_worktree_qualified(tmp_path: Path, snapshot: object) -> None:
    """The recovery instruction directory-qualifies each git command to the worktree."""
    instruction, phase = await _drive_integrate(
        tmp_path=tmp_path,
        seed_phase=IntegrationPhase.PUSH_REJECTED,
        landed_sha="localhead0005",
        fake_git=_make_fake_git(),
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
        fake_git=_make_fake_git(push_rc=0, is_ancestor=True),
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
        fake_git=_recording_fake_git(records, push_rc=0, is_ancestor=True),
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
        fake_git=_recording_fake_git(records, push_rc=0, is_ancestor=True, add_rc=1),
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
        fake_git=_recording_fake_git(records, push_rc=0, is_ancestor=True, staged_dirty=True, commit_rc=1),
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
        fake_git=_recording_fake_git(records, push_rc=0, is_ancestor=True),
        reconcile_side_effect=OSError("simulated reconcile filesystem failure"),
    )

    assert phase is IntegrationPhase.DELIVERY_BOOKKEEPING
    assert not _pushed(records)
    assert _SLUG in instruction
    row = _todo_row(tmp_path)
    assert row is not None
    assert row.status != TodoStatus.DELIVERED
    assert row.delivered_commit is None
