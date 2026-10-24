"""Git operations — dirty checks, stash introspection, and worktree merges.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
    TodoStatus,
)
from teleclaude.core.checkout_roots import worktree_location
from teleclaude.core.next_machine._types import _WORKTREE_PREP_STATE_REL, upstream_keys_for
from teleclaude.core.next_machine._types import ARTIFACT_UPSTREAMS as ARTIFACT_UPSTREAMS  # re-export
from teleclaude.core.next_machine.file_io import read_text_sync, write_text_sync
from teleclaude.git import (
    GIT_EXECUTABLE,
    GitCommandError,
    InvalidGitRepositoryError,
    NoSuchPathError,
    Repo,
    no_autostash_env,
)
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import ArtifactEntry, DependencyEntry, DriftReviewedStamp, TodoState

logger = get_logger(__name__)

ArtifactDriftStatus = Literal["fresh", "pending", "cosmetic", "substantive"]
DRIFT_FRESH: ArtifactDriftStatus = "fresh"
DRIFT_PENDING: ArtifactDriftStatus = "pending"
DRIFT_COSMETIC: ArtifactDriftStatus = "cosmetic"
DRIFT_SUBSTANTIVE: ArtifactDriftStatus = "substantive"

_GIT_HEAD_REF = "HEAD"
_GIT_ORIGIN_MAIN_REF = "origin/main"
_GIT_FETCH_ORIGIN = "origin"
_GIT_FETCH_MAIN = "main"
_GIT_MERGE_NO_EDIT = "--no-edit"
_GIT_MERGE_NO_AUTOSTASH = "--no-autostash"
_GIT_MERGE_NO_OVERWRITE_IGNORE = "--no-overwrite-ignore"
_GIT_FIRST_PARENT_FLAG = "--first-parent"
_GIT_WRITE_TREE_FLAG = "--write-tree"
_GIT_RANGE_SEPARATOR = ".."
_GIT_OUTPUT_LINE_SEPARATOR = "\n"
_GIT_SUCCESS_STATUS = 0
_GIT_MERGE_CONFLICT_STATUS = 1
_EMPTY_SHA = ""
_GIT_LOG_ALL_PATHS = "."
_GIT_PATHSPEC_SEPARATOR = "--"
_GIT_HEAD_RANGE_TEMPLATE = "{base}..HEAD"
_TODO_CHANGE_UNDETERMINED_MESSAGE = "todo_change_since_undetermined"
_WORKTREE_REPOSITORY_UNAVAILABLE_MESSAGE = "Worktree repository is unavailable."
_WORKTREE_FETCH_UNAVAILABLE_MESSAGE = "Unable to fetch origin/main."
_INVALID_WORKTREE_REPOSITORY_LOG_MESSAGE = "Invalid git repository at %s"
_SKIPPING_ORIGIN_MAIN_MERGE_LOG_TEMPLATE = "Skipping origin/main merge for %s — fetch failed: %s"
_ORIGIN_MAIN_MERGED_LOG_TEMPLATE = "Merged origin/main into worktree %s"
_WORKTREE_MERGE_FAILURE_TEMPLATE = (
    "Merge origin/main into worktree {slug} failed with conflicts. "
    "The merge was aborted. Resolve manually or rebase.\n{details}"
)

_ARTIFACT_TO_STATE_KEY: dict[str, str] = {
    STATE_KEY_INPUT: STATE_KEY_INPUT,
    STATE_KEY_PRD: STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS: STATE_KEY_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE: STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN: STATE_KEY_IMPLEMENTATION_PLAN,
    ARTIFACT_IMPLEMENTATION_PLAN: STATE_KEY_IMPLEMENTATION_PLAN,
}

_STATE_KEY_TO_ARTIFACT: dict[str, str] = {
    STATE_KEY_INPUT: STATE_KEY_INPUT,
    STATE_KEY_PRD: STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS: STATE_KEY_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE: STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN: ARTIFACT_IMPLEMENTATION_PLAN,
}

DEPENDENCY_ARTIFACT_KEYS: tuple[str, ...] = (
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
)


@dataclass(frozen=True)
class DependencyArtifactSnapshot:
    """Current lifecycle status and present artifact digests for one dependency."""

    status: TodoStatus
    digests: dict[str, str]


DependencyArtifactSnapshots = dict[str, DependencyArtifactSnapshot]


class DependencyStatusReader(Protocol):
    """Boundary for reading a todo's direct dependency status and persisted state."""

    async def get_deps_with_status(self, slug: str) -> list[DependencyEntry]:
        """Return immediate dependency slugs with todo status."""
        ...

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Return persisted todo state for a dependency slug."""
        ...


# ---------------------------------------------------------------------------
# Git primitives (public, consumed by work dispatch and phase derivation)
# ---------------------------------------------------------------------------


def get_head_commit(cwd: str) -> str:
    """Return HEAD commit hash for cwd, or empty string when unavailable."""
    try:
        repo = Repo(cwd)
        result: str = repo.git.rev_parse("HEAD").strip()
        return result
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning("head_commit_missing", cwd=cwd, reason=str(exc))
        return ""


def get_origin_main_sha(cwd: str) -> str:
    """Return origin/main SHA as the canonical drift anchor, or empty when unresolved."""
    try:
        repo = Repo(cwd)
    except (InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning("origin_main_fetch_failed", cwd=cwd, reason=str(exc))
        return ""

    try:
        repo.git.fetch("origin", "main")
    except (GitCommandError, OSError) as exc:
        logger.warning("origin_main_fetch_failed", cwd=cwd, reason=str(exc))

    try:
        result: str = repo.git.rev_parse("origin/main").strip()
        return result
    except (GitCommandError, OSError) as exc:
        logger.warning("origin_main_missing", cwd=cwd, reason=str(exc))
        return ""


def get_ref_commit(cwd: str, ref: str) -> str:
    """Return commit hash for a git ref in cwd, or empty string when unavailable."""
    try:
        repo = Repo(cwd)
        result: str = repo.git.rev_parse(ref).strip()
        return result
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning("ref_commit_missing", cwd=cwd, ref=ref, reason=str(exc))
        return ""


def get_remote_branch_head(cwd: str, branch: str) -> str:
    """Return origin/<branch> HEAD commit, or empty string when unavailable."""
    try:
        repo = Repo(cwd)
        # GitPython types every command result as any output mode; default invocation returns text.
        output = cast(str, repo.git.ls_remote("origin", f"refs/heads/{branch}"))
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning("remote_branch_head_missing", cwd=cwd, branch=branch, reason=str(exc))
        return ""
    parts = output.split()
    return parts[0] if parts else ""


def has_build_commits_beyond_main(worktree_cwd: str) -> bool:
    """Return True when the worktree has a file-changing commit ahead of main."""
    try:
        repo = Repo(worktree_cwd)
        base = repo.git.merge_base("HEAD", "origin/main").strip()
        log_output = repo.git.log(
            "--oneline",
            _GIT_HEAD_RANGE_TEMPLATE.format(base=base),
            _GIT_PATHSPEC_SEPARATOR,
            _GIT_LOG_ALL_PATHS,
        )
        return bool(log_output.strip())
    except (GitCommandError, OSError) as exc:
        logger.warning(
            "Failed to determine whether build commits exist beyond main",
            worktree_cwd=worktree_cwd,
            error=str(exc),
        )
        raise


def run_git_command(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        repo = Repo(cwd, search_parent_directories=True)
        output = str(repo.git.execute([GIT_EXECUTABLE, *args]))
        return 0, output, ""
    except (InvalidGitRepositoryError, NoSuchPathError):
        return 128, "", "not a git repository"
    except GitCommandError as exc:
        rc = exc.status if isinstance(exc.status, int) else 1
        return rc, exc.stdout or "", exc.stderr or ""


def _meaningful_changed_files_between(cwd: str, baseline: str, head: str) -> list[str] | None:
    """Return non-infrastructure files touched by non-merge commits, or None on git errors."""
    infra_prefixes = (".teleclaude/",)
    try:
        repo = Repo(cwd)
        log_output = repo.git.log(
            "--no-merges",
            "--name-only",
            "--pretty=format:",
            f"{baseline}..{head}",
        )
    except (GitCommandError, OSError) as exc:
        logger.warning(
            "drift file scan failed; treating drift as pending",
            cwd=cwd,
            baseline=baseline,
            head=head,
            error=str(exc),
        )
        return None
    return sorted(
        {
            path.strip()
            for path in log_output.splitlines()
            if path.strip() and not any(path.startswith(prefix) for prefix in infra_prefixes)
        }
    )


def _path_overlaps_reference(path: str, reference: str) -> bool:
    """Return True when a changed path is inside a referenced path surface."""
    normalized_path = path.strip().lstrip("./")
    normalized_reference = reference.strip().lstrip("./").rstrip("/")
    if not normalized_path or not normalized_reference:
        return False
    return normalized_path == normalized_reference or normalized_path.startswith(f"{normalized_reference}/")


def _commits_overlap_references(
    cwd: str,
    baseline: str,
    head: str,
    referenced_paths: list[str],
) -> bool | None:
    """Return whether non-merge commits in ``baseline..head`` change a referenced path, or None on git errors."""
    changed_files = _meaningful_changed_files_between(cwd, baseline, head)
    if changed_files is None:
        return None
    return any(_path_overlaps_reference(path, reference) for path in changed_files for reference in referenced_paths)


def extract_referenced_paths(content: str) -> list[str]:
    """Return paths declared in fenced referenced-paths blocks."""
    references: set[str] = set()
    in_referenced_paths_block = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if in_referenced_paths_block:
            if line.startswith("```"):
                in_referenced_paths_block = False
                continue
            if line and not line.startswith("#"):
                references.add(line)
            continue

        if not line.startswith("```"):
            continue
        info = line[3:].strip()
        language = info.split(maxsplit=1)[0] if info else ""
        if language == "referenced-paths":
            in_referenced_paths_block = True
    return sorted(references)


def derive_artifact_drift(
    artifact_entry: ArtifactEntry,
    drift_reviewed_stamp: DriftReviewedStamp | None,
    repo_root: str,
) -> ArtifactDriftStatus:
    """Derive artifact drift from recorded provenance and current git state.

    ``pending`` is fail-safe: if an artifact names referenced code but the git
    comparison cannot prove freshness, a drift-review worker must inspect it.
    """
    if not artifact_entry.digest and not artifact_entry.produced_at:
        return DRIFT_FRESH
    if not artifact_entry.referenced_paths:
        return DRIFT_FRESH
    current_head_sha = get_origin_main_sha(repo_root) if repo_root else ""
    if not artifact_entry.codebase_sha_at_write or not current_head_sha:
        return _reviewed_verdict_or_pending(drift_reviewed_stamp)
    if artifact_entry.codebase_sha_at_write == current_head_sha:
        return DRIFT_FRESH

    has_overlap = _commits_overlap_references(
        repo_root,
        artifact_entry.codebase_sha_at_write,
        current_head_sha,
        artifact_entry.referenced_paths,
    )
    if has_overlap is None:
        return _reviewed_verdict_or_pending(drift_reviewed_stamp)
    if not has_overlap:
        return DRIFT_FRESH

    def review_still_holds(reviewed: DriftReviewedStamp) -> bool:
        if not reviewed.head_sha_at_review:
            return False
        if reviewed.head_sha_at_review == current_head_sha:
            return True
        overlap_since_review = _commits_overlap_references(
            repo_root,
            reviewed.head_sha_at_review,
            current_head_sha,
            artifact_entry.referenced_paths,
        )
        return overlap_since_review is False

    return _reviewed_verdict_or_pending(
        drift_reviewed_stamp,
        evidence_matches_review=review_still_holds,
        require_evidence_for_substantive=True,
    )


def derive_upstream_artifact_drift(model: TodoState, artifact_name: str) -> ArtifactDriftStatus:
    """Derive drift between an artifact and the current digests of its upstream artifacts."""
    state_key = _state_key_for_artifact(artifact_name)
    entry = getattr(model.artifacts, state_key)
    if _artifact_is_absent(entry):
        return DRIFT_FRESH
    upstream_keys = upstream_keys_for(model.kind, state_key)
    if not upstream_keys:
        return DRIFT_FRESH
    current = {key: getattr(model.artifacts, key).digest for key in upstream_keys}
    if entry.upstream_digests == current:
        return DRIFT_FRESH
    stamp = _drift_stamp_for_artifact(model, state_key)
    if _has_missing_required_upstream(model, state_key, current):
        return _reviewed_verdict_or_pending(stamp)
    return _reviewed_verdict_or_pending(
        stamp,
        evidence_matches_review=lambda reviewed: reviewed.upstream_digests_at_review == current,
    )


def build_dependency_artifact_snapshot(
    dependencies: list[tuple[str, TodoStatus]],
    state_for: Callable[[str], TodoState | None],
) -> DependencyArtifactSnapshots:
    """Capture current dependency status and non-empty tracked artifact digests."""
    snapshot: DependencyArtifactSnapshots = {}
    for dep_slug, status in dependencies:
        state = state_for(dep_slug)
        digests = (
            {
                state_key: entry.digest
                for state_key in DEPENDENCY_ARTIFACT_KEYS
                if (entry := getattr(state.artifacts, state_key)).digest
            }
            if state is not None
            else {}
        )
        snapshot[dep_slug] = DependencyArtifactSnapshot(status=status, digests=digests)
    return snapshot


def dependency_artifact_evidence(
    recorded: dict[str, dict[str, str]],
    snapshot: DependencyArtifactSnapshots,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Compare recorded dependency keys that are still active or iceboxed."""
    current_evidence: dict[str, dict[str, str]] = {}
    moved_dependencies: list[str] = []
    for dep_slug, recorded_digests in recorded.items():
        dependency = snapshot.get(dep_slug)
        if dependency is None or dependency.status not in (TodoStatus.ACTIVE, TodoStatus.ICEBOX):
            continue
        current_digests = {key: dependency.digests.get(key, "") for key in recorded_digests}
        current_evidence[dep_slug] = current_digests
        if any(current_digests[key] != digest for key, digest in recorded_digests.items()):
            moved_dependencies.append(dep_slug)
    return current_evidence, moved_dependencies


def derive_dependency_artifact_drift(
    model: TodoState,
    snapshot: DependencyArtifactSnapshots,
) -> ArtifactDriftStatus:
    """Derive implementation-plan drift from recorded undelivered dependencies."""
    plan = model.artifacts.implementation_plan
    if _artifact_is_absent(plan) or not plan.dependency_artifact_digests:
        return DRIFT_FRESH
    current_evidence, moved_dependencies = dependency_artifact_evidence(
        plan.dependency_artifact_digests,
        snapshot,
    )
    if not moved_dependencies:
        return DRIFT_FRESH
    stamp = _drift_stamp_for_artifact(model, STATE_KEY_IMPLEMENTATION_PLAN)
    return _reviewed_verdict_or_pending(
        stamp,
        evidence_matches_review=lambda reviewed: _dependency_evidence_matches_review(
            reviewed.dependency_digests_at_review,
            current_evidence,
        ),
    )


def _dependency_evidence_matches_review(
    anchor: dict[str, dict[str, str]],
    current_evidence: dict[str, dict[str, str]],
) -> bool:
    """Match every currently evaluated dependency digest against its review anchor."""
    return all(
        anchor.get(dep_slug, {}).get(state_key) == digest
        for dep_slug, digests in current_evidence.items()
        for state_key, digest in digests.items()
    )


def _has_missing_required_upstream(
    model: TodoState,
    state_key: str,
    current_digests: dict[str, str],
) -> bool:
    return any(
        not digest and not _is_intentionally_absent_upstream(model, state_key, upstream_key)
        for upstream_key, digest in current_digests.items()
    )


def _is_intentionally_absent_upstream(model: TodoState, state_key: str, upstream_key: str) -> bool:
    entry = getattr(model.artifacts, state_key)
    if not entry.upstream_digests.get(upstream_key):
        # Structurally absent for this Todo's kind (e.g. diagnosis for a feature,
        # prd/architecture for a bug): the artifact was authored with this upstream
        # empty, so an empty current digest is not a newly-missing required upstream.
        return True
    return (
        state_key == STATE_KEY_IMPLEMENTATION_PLAN
        and upstream_key == STATE_KEY_ARCHITECTURE
        and model.approvals.architecture_skipped is not None
    )


def derive_owned_snippet_drift(
    model: TodoState,
    artifact_name: str,
    *,
    snippet_digest_fn: Callable[[str], str],
) -> ArtifactDriftStatus:
    """Derive drift for snippets owned by the artifact's delivering todo."""
    state_key = _state_key_for_artifact(artifact_name)
    entry = getattr(model.artifacts, state_key)
    if _artifact_is_absent(entry):
        return DRIFT_FRESH
    stamp = _drift_stamp_for_artifact(model, state_key)
    if not entry.async_provenance_complete:
        return _reviewed_verdict_or_pending(stamp)
    current = _current_snippet_digests(entry.owned_snippet_digests, snippet_digest_fn=snippet_digest_fn)
    if current is None:
        return _reviewed_verdict_or_pending(stamp)
    if entry.owned_snippet_digests == current:
        return DRIFT_FRESH
    return _reviewed_verdict_or_pending(
        stamp,
        evidence_matches_review=lambda reviewed: _snippet_evidence_matches_review(
            reviewed.snippet_digests_at_review,
            current,
        ),
    )


def derive_upstream_snippet_drift(
    model: TodoState,
    artifact_name: str,
    *,
    snippet_digest_fn: Callable[[str], str],
) -> ArtifactDriftStatus:
    """Derive drift for snippets referenced by the artifact body."""
    state_key = _state_key_for_artifact(artifact_name)
    entry = getattr(model.artifacts, state_key)
    if _artifact_is_absent(entry):
        return DRIFT_FRESH
    stamp = _drift_stamp_for_artifact(model, state_key)
    if not entry.async_provenance_complete:
        return _reviewed_verdict_or_pending(stamp)
    current = _current_snippet_digests(entry.referenced_snippet_digests, snippet_digest_fn=snippet_digest_fn)
    if current is None:
        return _reviewed_verdict_or_pending(stamp)
    if entry.referenced_snippet_digests == current:
        return DRIFT_FRESH
    return _reviewed_verdict_or_pending(
        stamp,
        evidence_matches_review=lambda reviewed: _snippet_evidence_matches_review(
            reviewed.snippet_digests_at_review,
            current,
        ),
    )


def derive_age_drift(
    model: TodoState,
    artifact_name: str,
    *,
    age_window_seconds: int | None,
    now_iso: str | None = None,
    drift_reviewed_stamp: DriftReviewedStamp | None = None,
) -> ArtifactDriftStatus:
    """Derive age drift for one artifact; disabled when no age window is configured."""
    if age_window_seconds is None:
        return DRIFT_FRESH
    state_key = _state_key_for_artifact(artifact_name)
    entry = getattr(model.artifacts, state_key)
    if _artifact_is_absent(entry):
        return DRIFT_FRESH
    if not entry.produced_at:
        return _reviewed_verdict_or_pending(drift_reviewed_stamp)
    try:
        produced_at = _parse_iso_datetime(entry.produced_at)
        now = _parse_iso_datetime(now_iso) if now_iso else datetime.now(UTC)
    except ValueError:
        return _reviewed_verdict_or_pending(drift_reviewed_stamp)
    age_seconds = (now - produced_at).total_seconds()
    if age_seconds <= age_window_seconds:
        return DRIFT_FRESH
    return _reviewed_verdict_or_pending(
        drift_reviewed_stamp,
        evidence_matches_review=lambda reviewed: _review_is_within_age_window(
            reviewed,
            now=now,
            age_window_seconds=age_window_seconds,
        ),
    )


def _state_key_for_artifact(artifact_name: str) -> str:
    return _ARTIFACT_TO_STATE_KEY.get(artifact_name, artifact_name)


def _artifact_name_for_state_key(state_key: str) -> str:
    return _STATE_KEY_TO_ARTIFACT.get(state_key, state_key)


def _artifact_is_absent(entry: ArtifactEntry) -> bool:
    return not entry.digest and not entry.produced_at


def _drift_stamp_for_artifact(model: TodoState, state_key: str) -> DriftReviewedStamp | None:
    return model.approvals.drift_reviewed.get(
        _artifact_name_for_state_key(state_key)
    ) or model.approvals.drift_reviewed.get(state_key)


def _current_snippet_digests(
    recorded: dict[str, str],
    *,
    snippet_digest_fn: Callable[[str], str],
) -> dict[str, str] | None:
    current: dict[str, str] = {}
    for snippet_id in sorted(recorded):
        digest = snippet_digest_fn(snippet_id)
        if not digest:
            return None
        current[snippet_id] = digest
    return current


def _reviewed_verdict_or_pending(
    stamp: DriftReviewedStamp | None,
    *,
    evidence_matches_review: Callable[[DriftReviewedStamp], bool] | None = None,
    require_evidence_for_substantive: bool = False,
) -> ArtifactDriftStatus:
    if stamp is None:
        return DRIFT_PENDING
    if stamp.verdict == DRIFT_SUBSTANTIVE and not require_evidence_for_substantive:
        return DRIFT_SUBSTANTIVE
    if evidence_matches_review is None:
        return DRIFT_PENDING
    return stamp.verdict if evidence_matches_review(stamp) else DRIFT_PENDING


def _snippet_evidence_matches_review(anchor: dict[str, str], current_evidence: dict[str, str]) -> bool:
    for snippet_id, digest in current_evidence.items():
        if anchor.get(snippet_id) != digest:
            return False
    return True


def _review_is_within_age_window(
    stamp: DriftReviewedStamp,
    *,
    now: datetime,
    age_window_seconds: int,
) -> bool:
    if not stamp.stamped_at:
        return False
    try:
        stamped_at = _parse_iso_datetime(stamp.stamped_at)
    except ValueError:
        return False
    review_age_seconds = (now - stamped_at).total_seconds()
    return review_age_seconds <= age_window_seconds


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Async file helpers
# ---------------------------------------------------------------------------


async def read_text_async(path: Path) -> str:
    """Read text from a file without blocking the event loop."""
    return await asyncio.to_thread(read_text_sync, path)


async def write_text_async(path: Path, content: str) -> None:
    """Write text to a file without blocking the event loop."""
    await asyncio.to_thread(write_text_sync, path, content)


# ---------------------------------------------------------------------------
# Git status helpers
# ---------------------------------------------------------------------------


def _dirty_paths(repo: Repo) -> list[str]:
    """Return dirty paths from porcelain status output."""
    lines = repo.git.status("--porcelain").splitlines()
    paths: list[str] = []
    for line in lines:
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.append(path)
    return paths


def build_git_hook_env(project_root: str, base_env: dict[str, str]) -> dict[str, str]:
    """Build environment variables for git hooks, ensuring venv/bin is in PATH."""
    env = base_env.copy()
    venv_bin = str(Path(project_root) / ".venv" / "bin")
    path = env.get("PATH", "")
    parts = path.split(os.pathsep)
    if venv_bin not in parts:
        parts.insert(0, venv_bin)
    else:
        # Move to front if already present
        parts.remove(venv_bin)
        parts.insert(0, venv_bin)
    env["PATH"] = os.pathsep.join(parts)
    env["VIRTUAL_ENV"] = str(Path(project_root) / ".venv")
    return env


def has_uncommitted_changes(cwd: str, slug: str) -> bool:
    """Check if worktree has uncommitted changes.

    Args:
        cwd: Project root directory
        slug: Work item slug (worktree is at trees/{slug})

    Returns:
        True if there are non-orchestrator uncommitted changes (staged or unstaged)
    """
    worktree_path = worktree_location(cwd, slug)[0]
    if not worktree_path.exists():
        return False

    try:
        repo = Repo(worktree_path)
        dirty_paths = _dirty_paths(repo)
        if not dirty_paths:
            return False

        # Orchestrator control files are expected to drift while mirroring main
        # planning state into worktrees.
        ignored = {
            ".teleclaude",
            ".teleclaude/",
            _WORKTREE_PREP_STATE_REL,
        }
        for path in dirty_paths:
            normalized = path.replace("\\", "/")
            if normalized.startswith(".teleclaude/"):
                continue
            if normalized not in ignored:
                return True
        return False
    except InvalidGitRepositoryError:
        logger.warning("Invalid git repository at %s", worktree_path)
        return False


def get_stash_entries(cwd: str) -> list[str]:
    """Return git stash entries for the repository at cwd.

    Stash state is repository-wide (shared by all worktrees), so this check is
    intentionally evaluated at repo scope.
    """
    try:
        repo = Repo(cwd)
        raw = cast(str, repo.git.stash("list"))
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except (InvalidGitRepositoryError, NoSuchPathError):
        logger.warning("Invalid git repository path for stash lookup: %s", cwd)
        return []
    except GitCommandError as exc:
        logger.warning("Unable to read git stash list at %s: %s", cwd, exc)
        return []


def has_git_stash_entries(cwd: str) -> bool:
    """Return True when repository stash contains one or more entries."""
    return bool(get_stash_entries(cwd))


# ---------------------------------------------------------------------------
# Worktree git operations
# ---------------------------------------------------------------------------


class WorktreeMergeOutcome(StrEnum):
    """The result of synchronizing a todo worktree with origin/main."""

    MERGED = "merged"
    UP_TO_DATE = "up_to_date"
    DEFERRED_UNCOMMITTED = "deferred_uncommitted"
    DEFERRED_FINALIZE_CLAIM = "deferred_finalize_claim"
    FETCH_UNAVAILABLE = "fetch_unavailable"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class WorktreeMergeResult:
    """Outcome and Git evidence for one worktree merge attempt."""

    outcome: WorktreeMergeOutcome
    head_before: str
    head_after: str
    message: str


def _merge_origin_main_into_worktree(worktree_cwd: str, slug: str) -> WorktreeMergeResult:
    """Fetch and merge origin/main without mutating uncommitted work."""
    try:
        repo = Repo(worktree_cwd)
        head_before = repo.git.rev_parse(_GIT_HEAD_REF).strip()
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError, OSError) as exc:
        logger.warning(_INVALID_WORKTREE_REPOSITORY_LOG_MESSAGE, worktree_cwd)
        return WorktreeMergeResult(
            WorktreeMergeOutcome.FETCH_UNAVAILABLE,
            _EMPTY_SHA,
            _EMPTY_SHA,
            str(exc) or _WORKTREE_REPOSITORY_UNAVAILABLE_MESSAGE,
        )

    if _dirty_paths(repo):
        return WorktreeMergeResult(
            WorktreeMergeOutcome.DEFERRED_UNCOMMITTED,
            head_before,
            head_before,
            _EMPTY_SHA,
        )

    try:
        repo.git.fetch(_GIT_FETCH_ORIGIN, _GIT_FETCH_MAIN)
    except GitCommandError as exc:
        logger.info(_SKIPPING_ORIGIN_MAIN_MERGE_LOG_TEMPLATE, slug, str(exc).strip())
        return WorktreeMergeResult(
            WorktreeMergeOutcome.FETCH_UNAVAILABLE,
            head_before,
            head_before,
            _WORKTREE_FETCH_UNAVAILABLE_MESSAGE,
        )

    try:
        repo.git.merge(
            _GIT_ORIGIN_MAIN_REF,
            _GIT_MERGE_NO_EDIT,
            _GIT_MERGE_NO_AUTOSTASH,
            _GIT_MERGE_NO_OVERWRITE_IGNORE,
            env=no_autostash_env(),
        )
    except GitCommandError as exc:
        # Abort the failed merge so the worktree stays clean
        try:
            repo.git.merge("--abort")
        except GitCommandError:
            pass
        head_after = get_head_commit(worktree_cwd)
        return WorktreeMergeResult(
            WorktreeMergeOutcome.CONFLICT,
            head_before,
            head_after,
            _WORKTREE_MERGE_FAILURE_TEMPLATE.format(slug=slug, details=(exc.stderr or "").strip()),
        )

    logger.info(_ORIGIN_MAIN_MERGED_LOG_TEMPLATE, slug)
    head_after = get_head_commit(worktree_cwd)
    outcome = WorktreeMergeOutcome.MERGED if head_after != head_before else WorktreeMergeOutcome.UP_TO_DATE
    return WorktreeMergeResult(outcome, head_before, head_after, _EMPTY_SHA)


class TodoChangeSinceReview(StrEnum):
    """Whether todo-authored changes followed the reviewed commit."""

    UNCHANGED = "unchanged"
    CHANGED = "changed"
    UNDETERMINED = "undetermined"


def todo_change_since(worktree_cwd: str, reviewed_head: str) -> TodoChangeSinceReview:
    """Classify whether the todo added changes after a reviewed commit."""
    full_reviewed_head = reviewed_head
    current_head = _EMPTY_SHA
    origin_main = _EMPTY_SHA
    try:
        repo = Repo(worktree_cwd)
        current_head = repo.git.rev_parse(_GIT_HEAD_REF).strip()
        if not reviewed_head:
            raise ValueError(_TODO_CHANGE_UNDETERMINED_MESSAGE)
        full_reviewed_head = repo.git.rev_parse(reviewed_head).strip()
        if full_reviewed_head == current_head:
            return TodoChangeSinceReview.UNCHANGED

        origin_main = repo.git.rev_parse(_GIT_ORIGIN_MAIN_REF).strip()
        merge_base = repo.git.merge_base(full_reviewed_head, current_head).strip()
        if merge_base != full_reviewed_head:
            return TodoChangeSinceReview.CHANGED

        commits = repo.git.rev_list(
            _GIT_FIRST_PARENT_FLAG,
            full_reviewed_head + _GIT_RANGE_SEPARATOR + current_head,
        ).splitlines()
        for commit_sha in commits:
            commit = repo.commit(commit_sha)
            if len(commit.parents) != 2:
                return TodoChangeSinceReview.CHANGED

            first_parent_sha = commit.parents[0].hexsha
            second_parent_sha = commit.parents[1].hexsha
            second_parent_base = repo.git.merge_base(second_parent_sha, origin_main).strip()
            if second_parent_base != second_parent_sha:
                return TodoChangeSinceReview.CHANGED

            merge_tree_status, merge_tree_output, _ = repo.git.merge_tree(
                _GIT_WRITE_TREE_FLAG,
                first_parent_sha,
                second_parent_sha,
                with_extended_output=True,
                with_exceptions=False,
            )
            if merge_tree_status == _GIT_MERGE_CONFLICT_STATUS:
                return TodoChangeSinceReview.CHANGED
            if merge_tree_status != _GIT_SUCCESS_STATUS:
                raise ValueError(_TODO_CHANGE_UNDETERMINED_MESSAGE)
            merge_tree = merge_tree_output.split(_GIT_OUTPUT_LINE_SEPARATOR, 1)[0].strip()
            if not merge_tree:
                raise ValueError(_TODO_CHANGE_UNDETERMINED_MESSAGE)
            if commit.tree.hexsha != merge_tree:
                return TodoChangeSinceReview.CHANGED

        return TodoChangeSinceReview.UNCHANGED
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError) as exc:
        logger.warning(
            _TODO_CHANGE_UNDETERMINED_MESSAGE,
            reviewed_head=full_reviewed_head,
            current_head=current_head,
            origin_main=origin_main,
            error=str(exc),
        )
        return TodoChangeSinceReview.UNDETERMINED


__all__ = [
    "DEPENDENCY_ARTIFACT_KEYS",
    "DRIFT_COSMETIC",
    "DRIFT_FRESH",
    "DRIFT_PENDING",
    "DRIFT_SUBSTANTIVE",
    "ArtifactDriftStatus",
    "DependencyArtifactSnapshot",
    "DependencyArtifactSnapshots",
    "TodoChangeSinceReview",
    "WorktreeMergeOutcome",
    "WorktreeMergeResult",
    "_merge_origin_main_into_worktree",
    "build_dependency_artifact_snapshot",
    "build_git_hook_env",
    "dependency_artifact_evidence",
    "derive_age_drift",
    "derive_artifact_drift",
    "derive_dependency_artifact_drift",
    "derive_owned_snippet_drift",
    "derive_upstream_artifact_drift",
    "derive_upstream_snippet_drift",
    "extract_referenced_paths",
    "get_origin_main_sha",
    "get_stash_entries",
    "has_git_stash_entries",
    "has_uncommitted_changes",
    "read_text_async",
    "todo_change_since",
    "write_text_async",
]
