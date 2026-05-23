"""Git operations — dirty checks, stash introspection, worktree merges, agent guidance.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config as app_config
from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
    WORKTREE_DIR,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _WORKTREE_PREP_STATE_REL
from teleclaude.core.next_machine.file_io import read_text_sync, write_text_sync
from teleclaude.core.next_machine.kinds import PLAN_WITHOUT_INTENT_UPSTREAM_KINDS
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo, no_autostash_env
from teleclaude.types.todos import ArtifactEntry, DependencyEntry, DriftReviewedStamp, TodoState

logger = get_logger(__name__)

ArtifactDriftStatus = Literal["fresh", "pending", "cosmetic", "substantive"]
DRIFT_FRESH: ArtifactDriftStatus = "fresh"
DRIFT_PENDING: ArtifactDriftStatus = "pending"
DRIFT_COSMETIC: ArtifactDriftStatus = "cosmetic"
DRIFT_SUBSTANTIVE: ArtifactDriftStatus = "substantive"

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

_ARTIFACT_UPSTREAMS: dict[str, tuple[str, ...]] = {
    STATE_KEY_PRD: (STATE_KEY_INPUT,),
    STATE_KEY_ARCHITECTURE: (STATE_KEY_PRD,),
    STATE_KEY_IMPLEMENTATION_PLAN: (STATE_KEY_PRD, STATE_KEY_ARCHITECTURE),
}


class DependencyStatusReader(Protocol):
    """Boundary needed by dependency-graph drift derivation."""

    async def get_deps_with_status(self, slug: str) -> list[DependencyEntry]:
        """Return immediate dependency slugs with todo status."""
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
    """Return origin/main SHA as the canonical drift anchor, or empty when unavailable."""
    try:
        repo = Repo(cwd)
        repo.git.fetch("origin", "main")
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning("origin_main_fetch_failed", cwd=cwd, reason=str(exc))
        return ""

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
        output = repo.git.ls_remote("origin", f"refs/heads/{branch}").strip()
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning("remote_branch_head_missing", cwd=cwd, branch=branch, reason=str(exc))
        return ""
    parts = output.split()
    return parts[0] if parts else ""


def has_build_commits_beyond_main(worktree_cwd: str) -> bool:
    """Return True when the worktree branch has commits ahead of main."""
    try:
        repo = Repo(worktree_cwd)
        base = repo.git.merge_base("HEAD", "main").strip()
        log_output = repo.git.log("--oneline", f"{base}..HEAD")
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
        output = str(repo.git.execute(["git", *args]))
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


def extract_referenced_paths(content: str, repo_root: str) -> list[str]:
    """Return tracked repo paths whose literals are referenced by artifact content."""
    try:
        repo = Repo(repo_root, search_parent_directories=True)
        tracked_output = repo.git.ls_files()
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError):
        return []
    references = {
        path.strip()
        for path in tracked_output.splitlines()
        if path.strip() and path.strip() in content and not path.strip().startswith(".teleclaude/")
    }
    return sorted(references)


def derive_artifact_drift(
    artifact_entry: ArtifactEntry,
    drift_reviewed_stamp: DriftReviewedStamp | None,
    _current_head_sha: str,
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

    changed_files = _meaningful_changed_files_between(
        repo_root,
        artifact_entry.codebase_sha_at_write,
        current_head_sha,
    )
    if changed_files is None:
        return _reviewed_verdict_or_pending(drift_reviewed_stamp)

    has_overlap = any(
        _path_overlaps_reference(path, reference)
        for path in changed_files
        for reference in artifact_entry.referenced_paths
    )
    if not has_overlap:
        return DRIFT_FRESH
    return _reviewed_verdict_or_pending(
        drift_reviewed_stamp,
        evidence_matches_review=lambda reviewed: (
            bool(reviewed.head_sha_at_review) and reviewed.head_sha_at_review == current_head_sha
        ),
        require_evidence_for_substantive=True,
    )


def derive_upstream_artifact_drift(model: TodoState, artifact_name: str) -> ArtifactDriftStatus:
    """Derive drift between an artifact and the current digests of its upstream artifacts."""
    state_key = _state_key_for_artifact(artifact_name)
    entry = getattr(model.artifacts, state_key)
    if _artifact_is_absent(entry):
        return DRIFT_FRESH
    upstream_keys = _ARTIFACT_UPSTREAMS.get(state_key, ())
    if not upstream_keys:
        return DRIFT_FRESH
    if _has_intentional_plan_only_upstreams(model, state_key, upstream_keys, entry.upstream_digests):
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


def _has_intentional_plan_only_upstreams(
    model: TodoState,
    state_key: str,
    upstream_keys: tuple[str, ...],
    recorded_digests: dict[str, str],
) -> bool:
    if state_key != STATE_KEY_IMPLEMENTATION_PLAN or model.kind not in PLAN_WITHOUT_INTENT_UPSTREAM_KINDS:
        return False
    current_digests = [getattr(model.artifacts, upstream_key).digest for upstream_key in upstream_keys]
    return not any(current_digests) and not any(recorded_digests.values())


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


async def derive_dependency_graph_drift(
    slug: str,
    model: TodoState,
    artifact_name: str,
    *,
    todos_db: DependencyStatusReader,
) -> ArtifactDriftStatus:
    """Derive drift for the todo's immediate dependency set and direct dep statuses."""
    state_key = _state_key_for_artifact(artifact_name)
    entry = getattr(model.artifacts, state_key)
    if _artifact_is_absent(entry):
        return DRIFT_FRESH
    if not entry.async_provenance_complete:
        return DRIFT_PENDING
    current = _sorted_dependency_entries(await todos_db.get_deps_with_status(slug))
    recorded = _sorted_dependency_entries(entry.dependency_set_at_write)
    if recorded == current:
        return DRIFT_FRESH
    return _reviewed_verdict_or_pending(
        _drift_stamp_for_artifact(model, state_key),
        evidence_matches_review=lambda reviewed: reviewed.dep_set_at_review == current,
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


def _sorted_dependency_entries(entries: list[DependencyEntry]) -> list[DependencyEntry]:
    return sorted(entries, key=lambda entry: (entry.dep_slug, entry.roadmap_status))


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
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
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


def _merge_origin_main_into_worktree(worktree_cwd: str, slug: str) -> str:
    """Fetch and merge origin/main into the worktree branch.

    Returns empty string on success (including when fetch is unavailable),
    or an error message only when merge conflicts occur.
    """
    try:
        repo = Repo(worktree_cwd)
    except (InvalidGitRepositoryError, NoSuchPathError):
        logger.warning("Invalid git repository at %s", worktree_cwd)
        return ""

    # Defense-in-depth: commit any pending changes before merging.
    # Workers commit their own changes, so this should be a no-op. If it
    # isn't, something upstream failed to commit — surface the anomaly.
    status = repo.git.status("--porcelain")
    if status.strip():
        repo.git.add("-A")
        repo.git.commit("-m", f"chore(todo): pre-merge worktree sync for {slug}", "--no-verify")
        logger.warning("Pre-merge found dirty worktree for %s — committed pending changes", slug)

    try:
        repo.git.fetch("origin", "main")
    except GitCommandError as exc:
        # Fetch failure is non-fatal (no remote, offline, test env)
        logger.info("Skipping origin/main merge for %s — fetch failed: %s", slug, str(exc).strip())
        return ""

    try:
        repo.git.merge("origin/main", "--no-edit", "--no-autostash", env=no_autostash_env())
    except GitCommandError as exc:
        # Abort the failed merge so the worktree stays clean
        try:
            repo.git.merge("--abort")
        except GitCommandError:
            pass
        return (
            f"Merge origin/main into worktree {slug} failed with conflicts. "
            f"The merge was aborted. Resolve manually or rebase.\n{(exc.stderr or '').strip()}"
        )

    logger.info("Merged origin/main into worktree %s", slug)
    return ""


def _has_meaningful_diff(cwd: str, baseline: str, head: str) -> bool:
    """Return True if non-infrastructure commits exist between baseline and head.

    Filters out:
    - Files under .teleclaude/
    - Files changed exclusively by merge commits

    Computes files changed by non-merge commits directly (via --no-merges) rather than
    subtracting merge-commit files from the total diff. This avoids the over-subtraction
    bug where a file touched by both a merge commit and a regular commit would be
    incorrectly excluded, producing a false negative and allowing a stale approval through.

    Returns True on git errors (fail-safe: assume meaningful diff, invalidate).
    """
    infra_prefixes = (".teleclaude/",)
    try:
        repo = Repo(cwd)
        log_output = repo.git.log(
            "--no-merges",
            "--name-only",
            "--pretty=format:",
            f"{baseline}..{head}",
        )
        meaningful_files = {
            f for f in log_output.splitlines() if f.strip() and not any(f.startswith(p) for p in infra_prefixes)
        }
        return bool(meaningful_files)
    except (GitCommandError, OSError) as exc:
        logger.warning(
            "has_meaningful_diff: git error; assuming meaningful diff (fail-safe)",
            extra={"cwd": cwd, "baseline": baseline, "head": head, "error": str(exc)},
        )
        return True  # Fail-safe: assume meaningful diff, invalidate approval


def review_surface_overlap_files(cwd: str, previous_head: str, current_head: str) -> list[str]:
    """Return overlapping meaningful files between newly merged commits and the current review surface."""
    infra_prefixes = (".teleclaude/",)
    try:
        repo = Repo(cwd)
        landed_output = repo.git.log(
            "--no-merges",
            "--name-only",
            "--pretty=format:",
            f"{previous_head}..{current_head}",
        )
        landed_files = {
            path
            for path in landed_output.splitlines()
            if path.strip() and not any(path.startswith(prefix) for prefix in infra_prefixes)
        }
        if not landed_files:
            return []

        surface_output = repo.git.diff("--name-only", "origin/main...HEAD")
        surface_files = {
            path
            for path in surface_output.splitlines()
            if path.strip() and not any(path.startswith(prefix) for prefix in infra_prefixes)
        }
        if not surface_files:
            return []
        return sorted(landed_files & surface_files)
    except (GitCommandError, OSError) as exc:
        logger.warning(
            "review_surface_overlap_files failed",
            extra={"cwd": cwd, "previous_head": previous_head, "current_head": current_head, "error": str(exc)},
        )
        return []


# ---------------------------------------------------------------------------
# Agent availability guidance
# ---------------------------------------------------------------------------


async def compose_agent_guidance(db: Db) -> str:
    """Compose runtime availability guidance for agent selection.

    Agent characteristics (strengths, cognitive profiles) are documented in the
    baseline concept snippet 'general/concept/agent-characteristics' and loaded
    into every agent's context. This function only adds runtime availability
    information (enabled/disabled, degraded status).
    """
    lines = ["AGENT SELECTION GUIDANCE:"]
    lines.append("")
    lines.append("Agent characteristics are in your baseline context (Agent Characteristics concept).")
    lines.append("Runtime availability:")

    # Clear expired availability first
    await db.clear_expired_agent_availability()

    listed_count = 0

    for agent_name in AgentName:
        name = agent_name.value
        cfg = app_config.agents.get(name)
        if not cfg or not cfg.enabled:
            continue

        # Check runtime status
        availability_raw = await db.get_agent_availability(name)
        availability = availability_raw if isinstance(availability_raw, dict) else None
        status_note = ""
        if availability:
            status = availability.get("status")
            if status == "unavailable":
                continue  # Skip completely
            if status == "degraded":
                reason = availability.get("reason", "unknown reason")
                status_note = f" [DEGRADED: {reason}]"

        listed_count += 1
        if status_note:
            lines.append(f"- {name.upper()}{status_note}")
        else:
            lines.append(f"- {name.upper()}: available")

    if listed_count == 0:
        raise RuntimeError("No agents are currently enabled and available.")

    lines.append("")
    lines.append("THINKING MODES:")
    lines.append("- fast: simple tasks, text editing, quick logic")
    lines.append("- med: standard coding, refactoring, review")
    lines.append("- slow: complex reasoning, architecture, planning, root cause analysis")

    return "\n".join(lines)


__all__ = [
    "DRIFT_COSMETIC",
    "DRIFT_FRESH",
    "DRIFT_PENDING",
    "DRIFT_SUBSTANTIVE",
    "ArtifactDriftStatus",
    "_has_meaningful_diff",
    "_merge_origin_main_into_worktree",
    "build_git_hook_env",
    "compose_agent_guidance",
    "derive_age_drift",
    "derive_artifact_drift",
    "derive_dependency_graph_drift",
    "derive_owned_snippet_drift",
    "derive_upstream_artifact_drift",
    "derive_upstream_snippet_drift",
    "extract_referenced_paths",
    "get_origin_main_sha",
    "get_stash_entries",
    "has_git_stash_entries",
    "has_uncommitted_changes",
    "read_text_async",
    "write_text_async",
]
