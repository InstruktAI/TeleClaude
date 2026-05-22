"""Characterization tests for git policy helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from git.exc import GitCommandError

from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    _has_meaningful_diff,
    build_git_hook_env,
    compose_agent_guidance,
    derive_artifact_drift,
    get_head_commit,
    get_origin_main_sha,
    get_ref_commit,
    get_remote_branch_head,
    get_stash_entries,
    has_build_commits_beyond_main,
    has_uncommitted_changes,
    review_surface_overlap_files,
)
from teleclaude.types.todos import ArtifactEntry, DependencyEntry, DriftReviewedStamp, TodoState

_ORIGIN_MAIN_SHA = "origin-main-sha"
_LOCAL_MAIN_SHA = "local-main-sha"


def test_build_git_hook_env_moves_venv_bin_to_front_and_sets_virtual_env(tmp_path: Path) -> None:
    env = build_git_hook_env(str(tmp_path), {"PATH": "/usr/bin:/bin"})

    assert env["PATH"].split(":", maxsplit=1)[0] == str(tmp_path / ".venv" / "bin")
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")


def test_has_uncommitted_changes_ignores_orchestrator_paths(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-a"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=SimpleNamespace()),
        patch(
            "teleclaude.core.next_machine.git_ops._dirty_paths",
            return_value=[".teleclaude/runtime.json"],
        ),
    ):
        dirty = has_uncommitted_changes(str(tmp_path), "slug-a")

    assert dirty is False


def test_has_uncommitted_changes_flags_unrelated_worktree_paths(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-b"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=SimpleNamespace()),
        patch("teleclaude.core.next_machine.git_ops._dirty_paths", return_value=["src/app.py"]),
    ):
        dirty = has_uncommitted_changes(str(tmp_path), "slug-b")

    assert dirty is True


def test_get_stash_entries_returns_empty_on_git_command_error(tmp_path: Path) -> None:
    repo = SimpleNamespace(git=SimpleNamespace(stash=lambda *_args: (_ for _ in ()).throw(GitCommandError("stash", 1))))

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        entries = get_stash_entries(str(tmp_path))

    assert entries == []


def test_get_origin_main_sha_returns_remote_main_sha() -> None:
    repo = MagicMock()
    repo.git.rev_parse.return_value = _ORIGIN_MAIN_SHA

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        sha = get_origin_main_sha("/repo")

    repo.git.fetch.assert_called_once()
    repo.git.rev_parse.assert_called_once()
    assert sha == _ORIGIN_MAIN_SHA


def test_get_origin_main_sha_returns_empty_when_fetch_fails() -> None:
    repo = MagicMock()
    repo.git.fetch.side_effect = GitCommandError("fetch", 1)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo),
        patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning,
    ):
        sha = get_origin_main_sha("/repo")

    assert sha == ""
    repo.git.rev_parse.assert_not_called()
    mock_warning.assert_called_once()


def test_get_origin_main_sha_returns_empty_when_origin_main_is_missing() -> None:
    repo = MagicMock()
    repo.git.rev_parse.side_effect = GitCommandError("rev-parse", 1)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo),
        patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning,
    ):
        sha = get_origin_main_sha("/repo")

    assert sha == ""
    mock_warning.assert_called_once()


def test_get_origin_main_sha_does_not_fall_back_to_local_main() -> None:
    repo = MagicMock()

    def rev_parse(ref: str) -> str:
        if ref == "origin/main":
            raise GitCommandError("rev-parse", 1)
        return _LOCAL_MAIN_SHA

    repo.git.rev_parse.side_effect = rev_parse

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        sha = get_origin_main_sha("/repo")

    assert sha == ""
    repo.git.rev_parse.assert_called_once()


def test_get_head_commit_returns_empty_when_head_unavailable() -> None:
    repo = MagicMock()
    repo.git.rev_parse.side_effect = GitCommandError("rev-parse", 1)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo),
        patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning,
    ):
        sha = get_head_commit("/repo")

    assert sha == ""
    mock_warning.assert_called_once()


def test_get_ref_commit_returns_empty_when_ref_unavailable() -> None:
    repo = MagicMock()
    repo.git.rev_parse.side_effect = GitCommandError("rev-parse", 1)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo),
        patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning,
    ):
        sha = get_ref_commit("/repo", "feature-branch")

    assert sha == ""
    mock_warning.assert_called_once()


def test_get_remote_branch_head_returns_empty_when_branch_unavailable() -> None:
    repo = MagicMock()
    repo.git.ls_remote.side_effect = GitCommandError("ls-remote", 1)

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo),
        patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning,
    ):
        sha = get_remote_branch_head("/repo", "feature-branch")

    assert sha == ""
    mock_warning.assert_called_once()


def test_has_build_commits_beyond_main_propagates_git_command_error() -> None:
    repo = SimpleNamespace(
        git=SimpleNamespace(merge_base=lambda *_args: (_ for _ in ()).throw(GitCommandError("merge-base", 1)))
    )

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=repo):
        with patch("teleclaude.core.next_machine.git_ops.logger.warning") as mock_warning:
            with pytest.raises(GitCommandError):
                has_build_commits_beyond_main("/repo")

    mock_warning.assert_called_once()


def test_has_meaningful_diff_filters_infrastructure_only_changes() -> None:
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = ".teleclaude/run.json\n.teleclaude/todos.db\n"

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo):
        meaningful = _has_meaningful_diff("/repo", "base", "head")

    assert meaningful is False


def test_review_surface_overlap_files_returns_only_meaningful_overlap() -> None:
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = "src/feature.py\n.teleclaude/todos.db\nsrc/other.py\n"
    mock_repo.git.diff.return_value = "src/feature.py\n.teleclaude/runtime.json\n"

    with patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo):
        overlap = review_surface_overlap_files("/repo", "before", "after")

    assert overlap == ["src/feature.py"]


def test_derive_artifact_drift_fresh_when_head_matches_baseline() -> None:
    artifact = ArtifactEntry(digest="digest", codebase_sha_at_write="head", referenced_paths=["src/feature.py"])

    with patch("teleclaude.core.next_machine.git_ops.get_origin_main_sha", return_value="head"):
        status = derive_artifact_drift(artifact, None, "ignored", "/repo")

    assert status == DRIFT_FRESH


def test_derive_artifact_drift_pending_when_referenced_path_changed_without_review() -> None:
    artifact = ArtifactEntry(digest="digest", codebase_sha_at_write="base", referenced_paths=["src/feature.py"])
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = "src/feature.py\n"

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo),
        patch("teleclaude.core.next_machine.git_ops.get_origin_main_sha", return_value="head"),
    ):
        status = derive_artifact_drift(artifact, None, "ignored", "/repo")

    assert status == DRIFT_PENDING


def test_derive_artifact_drift_cosmetic_when_overlap_reviewed_cosmetic() -> None:
    artifact = ArtifactEntry(digest="digest", codebase_sha_at_write="base", referenced_paths=["src/feature.py"])
    stamp = DriftReviewedStamp(verdict="cosmetic", reason="docs only", stamped_at="now", head_sha_at_review="head")
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = "src/feature.py\n"

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo),
        patch("teleclaude.core.next_machine.git_ops.get_origin_main_sha", return_value="head"),
    ):
        status = derive_artifact_drift(artifact, stamp, "ignored", "/repo")

    assert status == DRIFT_COSMETIC


def test_derive_artifact_drift_substantive_when_reviewed_substantive() -> None:
    artifact = ArtifactEntry(digest="digest", codebase_sha_at_write="base", referenced_paths=["src/feature.py"])
    stamp = DriftReviewedStamp(verdict="substantive", reason="API changed", stamped_at="now", head_sha_at_review="head")
    mock_repo = MagicMock()
    mock_repo.git.log.return_value = "src/feature.py\n"

    with (
        patch("teleclaude.core.next_machine.git_ops.Repo", return_value=mock_repo),
        patch("teleclaude.core.next_machine.git_ops.get_origin_main_sha", return_value="head"),
    ):
        status = derive_artifact_drift(artifact, stamp, "ignored", "/repo")

    assert status == DRIFT_SUBSTANTIVE


async def test_compose_agent_guidance_lists_enabled_agents_and_skips_unavailable() -> None:
    db = AsyncMock()
    db.get_agent_availability.side_effect = [
        None,
        {"status": "degraded", "reason": "slow quota"},
        {"status": "unavailable"},
    ]
    app_config = SimpleNamespace(
        agents={
            "alpha": SimpleNamespace(enabled=True),
            "beta": SimpleNamespace(enabled=True),
            "gamma": SimpleNamespace(enabled=True),
        }
    )
    agent_names = [
        SimpleNamespace(value="alpha"),
        SimpleNamespace(value="beta"),
        SimpleNamespace(value="gamma"),
    ]

    with (
        patch("teleclaude.core.next_machine.git_ops.app_config", app_config),
        patch("teleclaude.core.next_machine.git_ops.AgentName", agent_names),
    ):
        guidance = await compose_agent_guidance(db)

    assert "- ALPHA: available" in guidance
    assert "- BETA [DEGRADED: slow quota]" in guidance
    assert "- GAMMA" not in guidance


# ── Per-class drift derivation helpers (merged from former test_git_ops_drift.py) ─────

from teleclaude.core.next_machine.git_ops import (  # noqa: E402
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    derive_age_drift,
    derive_artifact_drift,
    derive_dependency_graph_drift,
    derive_owned_snippet_drift,
    derive_upstream_artifact_drift,
    derive_upstream_snippet_drift,
)

_ARCHITECTURE = "architecture"
_IMPLEMENTATION_PLAN = "implementation-plan"
_IMPLEMENTATION_PLAN_STATE_KEY = "implementation_plan"
_PRD = "prd"
_SNIPPET_ID = "project/spec/example"
_STALE_DIGEST = "stale-digest"
_CURRENT_DIGEST = "current-digest"
_COSMETIC_REASON = "cosmetic"
_ACTIVE_STATUS = "active"
_DEPENDENCY_SLUG = "dependency"
_REFACTOR_KIND = "refactor"


class _FakeTodosDb:
    def __init__(self, deps: list[DependencyEntry]) -> None:
        self._deps = deps

    async def get_deps_with_status(self, _slug: str) -> list[DependencyEntry]:
        return self._deps


def _snippet_digest(snippet_id: str) -> str:
    return _CURRENT_DIGEST if snippet_id == _SNIPPET_ID else ""


def test_upstream_artifact_drift_is_fresh_when_recorded_digests_match_current_state() -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = _CURRENT_DIGEST
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.upstream_digests = {_PRD: _CURRENT_DIGEST}

    status = derive_upstream_artifact_drift(state, _ARCHITECTURE)

    assert status == DRIFT_FRESH


def test_upstream_artifact_drift_is_pending_when_recorded_digest_is_stale_without_anchor() -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = _CURRENT_DIGEST
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.upstream_digests = {_PRD: _STALE_DIGEST}

    status = derive_upstream_artifact_drift(state, _ARCHITECTURE)

    assert status == DRIFT_PENDING


def test_upstream_artifact_drift_uses_cosmetic_anchor_for_current_evidence() -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = _CURRENT_DIGEST
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.upstream_digests = {_PRD: _STALE_DIGEST}
    state.approvals.drift_reviewed[_ARCHITECTURE] = DriftReviewedStamp(
        verdict=DRIFT_COSMETIC,
        reason=_COSMETIC_REASON,
        upstream_digests_at_review={_PRD: _CURRENT_DIGEST},
    )

    status = derive_upstream_artifact_drift(state, _ARCHITECTURE)

    assert status == DRIFT_COSMETIC


def test_upstream_artifact_drift_ignores_absent_upstreams_for_plan_only_work() -> None:
    state = TodoState.defaults()
    state.kind = _REFACTOR_KIND
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.upstream_digests = {_PRD: "", _ARCHITECTURE: ""}
    state.approvals.drift_reviewed[_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict=DRIFT_SUBSTANTIVE,
        reason="missing upstreams",
        upstream_digests_at_review={_PRD: "", _ARCHITECTURE: ""},
    )

    status = derive_upstream_artifact_drift(state, _IMPLEMENTATION_PLAN)

    assert status == DRIFT_FRESH


def test_code_drift_ignores_substantive_stamp_when_code_evidence_is_fresh() -> None:
    entry = ArtifactEntry(digest="plan-digest", referenced_paths=[])
    stamp = DriftReviewedStamp(verdict=DRIFT_SUBSTANTIVE, reason="upstream artifact changed")

    status = derive_artifact_drift(entry, stamp, "ignored", "/repo")

    assert status == DRIFT_FRESH


def test_owned_snippet_drift_is_pending_until_async_provenance_is_complete() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.owned_snippet_digests = {_SNIPPET_ID: _CURRENT_DIGEST}

    status = derive_owned_snippet_drift(state, _ARCHITECTURE, snippet_digest_fn=_snippet_digest)

    assert status == DRIFT_PENDING


def test_owned_snippet_drift_is_fresh_when_digests_match() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.async_provenance_complete = True
    state.artifacts.architecture.owned_snippet_digests = {_SNIPPET_ID: _CURRENT_DIGEST}

    status = derive_owned_snippet_drift(state, _ARCHITECTURE, snippet_digest_fn=_snippet_digest)

    assert status == DRIFT_FRESH


def test_upstream_snippet_drift_re_pends_when_cosmetic_anchor_is_stale() -> None:
    state = TodoState.defaults()
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.async_provenance_complete = True
    state.artifacts.implementation_plan.referenced_snippet_digests = {_SNIPPET_ID: _STALE_DIGEST}
    state.approvals.drift_reviewed[_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict=DRIFT_COSMETIC,
        reason=_COSMETIC_REASON,
        snippet_digests_at_review={_SNIPPET_ID: _STALE_DIGEST},
    )

    status = derive_upstream_snippet_drift(state, _IMPLEMENTATION_PLAN_STATE_KEY, snippet_digest_fn=_snippet_digest)

    assert status == DRIFT_PENDING


async def test_dependency_graph_drift_is_fresh_when_snapshot_matches_current_direct_deps() -> None:
    dep = DependencyEntry(dep_slug=_DEPENDENCY_SLUG, roadmap_status=_ACTIVE_STATUS)
    state = TodoState.defaults()
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.async_provenance_complete = True
    state.artifacts.implementation_plan.dependency_set_at_write = [dep]

    status = await derive_dependency_graph_drift(
        "child",
        state,
        _IMPLEMENTATION_PLAN_STATE_KEY,
        todos_db=_FakeTodosDb([dep]),
    )

    assert status == DRIFT_FRESH


async def test_dependency_graph_drift_is_pending_when_direct_dep_status_changes() -> None:
    recorded = DependencyEntry(dep_slug=_DEPENDENCY_SLUG, roadmap_status=_ACTIVE_STATUS)
    current = DependencyEntry(dep_slug=_DEPENDENCY_SLUG, roadmap_status="delivered")
    state = TodoState.defaults()
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.async_provenance_complete = True
    state.artifacts.implementation_plan.dependency_set_at_write = [recorded]

    status = await derive_dependency_graph_drift(
        "child",
        state,
        _IMPLEMENTATION_PLAN_STATE_KEY,
        todos_db=_FakeTodosDb([current]),
    )

    assert status == DRIFT_PENDING


def test_age_drift_is_fresh_when_age_window_is_disabled() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.produced_at = "2020-01-01T00:00:00+00:00"

    status = derive_age_drift(state, _ARCHITECTURE, age_window_seconds=None)

    assert status == DRIFT_FRESH


def test_age_drift_is_pending_when_artifact_is_older_than_window() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.produced_at = "2020-01-01T00:00:00+00:00"

    status = derive_age_drift(state, _ARCHITECTURE, age_window_seconds=1, now_iso="2020-01-01T00:00:02+00:00")

    assert status == DRIFT_PENDING
