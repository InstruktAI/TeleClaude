"""Worktree lifecycle — create, prep-state, and policy-based preparation.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    _PREP_INPUT_FILES,
    _PREP_ROOT_INPUT_FILES,
    _PREP_STATE_VERSION,
    _WORKTREE_PREP_STATE_REL,
    EnsureWorktreeResult,
    WorktreePrepDecision,
)
from teleclaude.core.next_machine.state_io import _file_sha256
from teleclaude.core.next_machine.worktree_home import ensure_worktree_home
from teleclaude.core.reconciliation.config_schemas import converge_project_schema_link
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, Repo
from teleclaude.runtime.agy_workspace_trust import add_worktree_trust

logger = get_logger(__name__)
_WORKTREE_SCHEMA_LINK_EVENT = "worktree_config_schema_link"
_WORKTREE_SCHEMA_LINK_FAILED_EVENT = "worktree_config_schema_link_failed"
_ORIGIN = "origin"
_MAIN_BRANCH = "main"
_ORIGIN_MAIN_REF = "origin/main"
_GIT_HEAD_REF = "HEAD"
_GIT_ADD = "add"
_GIT_BRANCH_CREATE = "-b"
_GIT_QUIET = "--quiet"
_GIT_IS_ANCESTOR = "--is-ancestor"
_GIT_FORCE_DELETE = "-D"
_GIT_ALLOW_EMPTY = "--allow-empty"
_GIT_AUTHOR = "--author"
_GIT_MESSAGE = "-m"
_LOCAL_BRANCH_REF_TEMPLATE = "refs/heads/{branch}"
_REMOTE_BRANCH_REF_TEMPLATE = "origin/{branch}"
_FETCH_BRANCH_REFS_TEMPLATE = "refs/heads/{branch}:refs/remotes/origin/{branch}"
_OPENING_COMMIT_MESSAGE_TEMPLATE = "chore(worktree): open {slug} for remote ownership"
_OPENING_COMMIT_IDENTITY_ERROR_TEMPLATE = (
    "Cannot create the todo opening commit without a resolved commit identity: {reason}"
)
_OPENING_COMMIT_AGENT_REQUIRED = "todo worktree creation requires an attributable agent session"
_REMOTE_REF_MISSING_TEXT = "couldn't find remote ref"
_EMPTY_SHA = ""
_WORKTREE_OPENED_EVENT = "worktree_opened"
_WORKTREE_MATERIALIZED_EVENT = "worktree_materialized_from_remote"
_WORKTREE_FAST_FORWARD_EVENT = "worktree_branch_fast_forwarded"
_WORKTREE_EMPTY_LEFTOVER_EVENT = "worktree_empty_leftover_replaced"
_WORKTREE_STARTED_WITHOUT_BRANCH_EVENT = "worktree_started_todo_branch_missing"
_WORKTREE_CREATE_FAILED_LOG = "Failed to create worktree for slug=%s cwd=%s worktree_path=%s"
_LEFTOVER_BRANCH_MESSAGE = (
    "Local branch {branch} contains file changes and cannot be assigned to this todo (tip {tip})."
)
_DIVERGED_BRANCH_MESSAGE = "Local branch {branch} at {local_tip} diverges from its remote todo branch at {remote_tip}."
_TODO_WORK_NOT_LOCATED_MESSAGE = (
    "Todo work from build-start commit {build_start_sha} was not found on its remote or local branch."
)


class LeftoverBranch(Exception):
    """A same-named local branch contains file changes with unknown todo ownership."""

    def __init__(self, branch: str, tip: str) -> None:
        self.branch = branch
        self.tip = tip
        super().__init__(_LEFTOVER_BRANCH_MESSAGE.format(branch=branch, tip=tip))


class WorktreeBranchDiverged(Exception):
    """The local and remote todo branches diverged and cannot be merged safely."""

    def __init__(self, branch: str, local_tip: str, remote_tip: str) -> None:
        self.branch = branch
        self.local_tip = local_tip
        self.remote_tip = remote_tip
        super().__init__(_DIVERGED_BRANCH_MESSAGE.format(branch=branch, local_tip=local_tip, remote_tip=remote_tip))


class TodoWorkNotLocated(Exception):
    """A started todo's branch cannot be proven from its build-start commit."""

    def __init__(self, build_start_sha: str) -> None:
        self.build_start_sha = build_start_sha
        super().__init__(_TODO_WORK_NOT_LOCATED_MESSAGE.format(build_start_sha=build_start_sha))


class WorktreeOpeningCommitIdentityError(Exception):
    """The opening commit cannot be attributed to a resolved agent session."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(_OPENING_COMMIT_IDENTITY_ERROR_TEMPLATE.format(reason=reason))


def _worktree_prep_state_path(cwd: str, slug: str) -> Path:
    """Get prep-state marker path inside worktree."""
    return Path(cwd) / WORKTREE_DIR / slug / _WORKTREE_PREP_STATE_REL


def _compute_prep_inputs_digest(cwd: str, slug: str) -> str:
    """Compute hash of dependency-installation inputs that impact prep."""
    project_root = Path(cwd)
    worktree_root = project_root / WORKTREE_DIR / slug
    digest = hashlib.sha256()

    candidates: list[tuple[str, Path]] = []
    for rel in _PREP_ROOT_INPUT_FILES:
        candidates.append((f"root:{rel}", project_root / rel))
    for rel in _PREP_INPUT_FILES:
        candidates.append((f"worktree:{rel}", worktree_root / rel))

    for label, path in sorted(candidates, key=lambda item: item[0]):
        digest.update(label.encode("utf-8"))
        exists = path.exists()
        digest.update(b"1" if exists else b"0")
        if not exists:
            continue
        is_executable = os.access(path, os.X_OK)
        digest.update(b"1" if is_executable else b"0")
        if path.is_file():
            digest.update(_file_sha256(path).encode("utf-8"))
    return digest.hexdigest()


def _read_worktree_prep_state(cwd: str, slug: str) -> dict[str, str] | None:
    """Read prep-state marker written after successful prep."""
    state_path = _worktree_prep_state_path(cwd, slug)
    if not state_path.exists():
        return None
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt worktree prep state at %s: %s — treating as missing, will re-prepare.", state_path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("version")
    digest = raw.get("inputs_digest")
    if not isinstance(version, int) or version != _PREP_STATE_VERSION:
        return None
    if not isinstance(digest, str) or not digest:
        return None
    return {"inputs_digest": digest}


def _write_worktree_prep_state(cwd: str, slug: str, inputs_digest: str) -> None:
    """Persist prep-state marker after successful preparation."""
    state_path = _worktree_prep_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _PREP_STATE_VERSION,
        "inputs_digest": inputs_digest,
        "prepared_at": datetime.now(UTC).isoformat(),
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _decide_worktree_prep(cwd: str, slug: str, created: bool) -> WorktreePrepDecision:
    """Decide whether prep is required for a slug worktree."""
    inputs_digest = _compute_prep_inputs_digest(cwd, slug)
    if created:
        return WorktreePrepDecision(should_prepare=True, reason="worktree_created", inputs_digest=inputs_digest)
    state = _read_worktree_prep_state(cwd, slug)
    if state is None:
        return WorktreePrepDecision(should_prepare=True, reason="prep_state_missing", inputs_digest=inputs_digest)
    if state.get("inputs_digest") != inputs_digest:
        return WorktreePrepDecision(should_prepare=True, reason="prep_inputs_changed", inputs_digest=inputs_digest)
    return WorktreePrepDecision(should_prepare=False, reason="unchanged_known_good", inputs_digest=inputs_digest)


def _create_or_attach_worktree(cwd: str, slug: str, *, build_start_sha: str) -> bool:
    """Ensure the slug worktree exists, resuming only a remote branch proven to belong to its todo."""
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if worktree_path.exists():
        return False

    try:
        repo = Repo(cwd)
    except InvalidGitRepositoryError:
        logger.error("Cannot create worktree: %s is not a git repository", cwd)
        raise

    trees_dir = Path(cwd) / WORKTREE_DIR
    trees_dir.mkdir(exist_ok=True)

    try:
        repo.git.fetch(_ORIGIN, _MAIN_BRANCH)
        if build_start_sha:
            _create_started_todo_worktree(repo, worktree_path, slug, build_start_sha)
        else:
            _create_new_todo_worktree(repo, worktree_path, slug)
    except Exception:
        logger.exception(_WORKTREE_CREATE_FAILED_LOG, slug, cwd, worktree_path)
        raise

    logger.info(_WORKTREE_OPENED_EVENT, slug=slug, path=str(worktree_path), head_sha=_resolve_head_sha(worktree_path))
    return True


def _create_new_todo_worktree(repo: Repo, worktree_path: Path, slug: str) -> None:
    """Create a new todo branch from origin/main and give it a unique opening commit."""
    opening_commit_args = _opening_commit_args(slug)
    main_sha = _resolve_ref_sha(repo, _ORIGIN_MAIN_REF)
    local_branch_exists = _has_local_branch(repo, slug)
    if local_branch_exists:
        local_tip = _resolve_branch_sha(repo, slug)
        try:
            base_sha = repo.git.merge_base(_ORIGIN_MAIN_REF, slug).strip()
            repo.git.diff(_GIT_QUIET, base_sha, slug)
        except GitCommandError as exc:
            if exc.status == 1:
                raise LeftoverBranch(slug, local_tip) from exc
            raise
        repo.git.branch(_GIT_FORCE_DELETE, slug)
        logger.info(_WORKTREE_EMPTY_LEFTOVER_EVENT, slug=slug, old_tip=local_tip, main_sha=main_sha)

    repo.git.worktree(_GIT_ADD, str(worktree_path), _GIT_BRANCH_CREATE, slug, _ORIGIN_MAIN_REF)
    worktree_repo = Repo(str(worktree_path))
    worktree_repo.git.commit(*opening_commit_args)


def _opening_commit_args(slug: str) -> list[str]:
    """Compose a todo opening commit with the shared author and footer contract."""
    from teleclaude.commit_identity import (  # noqa: PLC0415 - importing this helper at module load creates a next-machine cycle.
        CommitIdentityUnresolvable,
        compose_commit_footer,
        resolve_commit_identity,
    )

    try:
        git_identity, session_id = resolve_commit_identity()
    except CommitIdentityUnresolvable as exc:
        raise WorktreeOpeningCommitIdentityError(str(exc)) from exc
    if git_identity is None or session_id is None:
        raise WorktreeOpeningCommitIdentityError(_OPENING_COMMIT_AGENT_REQUIRED)

    message = compose_commit_footer(
        _OPENING_COMMIT_MESSAGE_TEMPLATE.format(slug=slug),
        session_id=session_id,
        human_involved=False,
    )
    args = [_GIT_ALLOW_EMPTY, _GIT_AUTHOR, git_identity]
    args.extend([_GIT_MESSAGE, message])
    return args


def _create_started_todo_worktree(repo: Repo, worktree_path: Path, slug: str, build_start_sha: str) -> None:
    """Attach or fast-forward the local branch only when its remote proves todo ownership.

    With no branch under the todo's name locally or on origin, there is no work to resume and the
    todo gets a fresh branch from origin/main.
    """
    fetch_ref = _FETCH_BRANCH_REFS_TEMPLATE.format(branch=slug)
    try:
        repo.git.fetch(_ORIGIN, fetch_ref)
    except GitCommandError as exc:
        if _REMOTE_REF_MISSING_TEXT not in str(exc).lower():
            raise
        remote_branch_exists = False
    else:
        remote_branch_exists = True

    remote_ref = _REMOTE_BRANCH_REF_TEMPLATE.format(branch=slug)
    remote_sha = _resolve_ref_sha(repo, remote_ref) if remote_branch_exists else _EMPTY_SHA
    own_remote_branch = (
        bool(remote_sha)
        and _is_ancestor(repo, build_start_sha, remote_ref)
        and not _is_ancestor(repo, build_start_sha, _ORIGIN_MAIN_REF)
    )
    if not own_remote_branch:
        if _has_local_branch(repo, slug):
            repo.git.worktree(_GIT_ADD, str(worktree_path), slug)
            return
        if not remote_branch_exists:
            logger.warning(_WORKTREE_STARTED_WITHOUT_BRANCH_EVENT, slug=slug, build_start_sha=build_start_sha)
            _create_new_todo_worktree(repo, worktree_path, slug)
            return
        raise TodoWorkNotLocated(build_start_sha)

    local_branch_ref = _LOCAL_BRANCH_REF_TEMPLATE.format(branch=slug)
    if not _has_local_branch(repo, slug):
        repo.git.worktree(_GIT_ADD, str(worktree_path), _GIT_BRANCH_CREATE, slug, remote_ref)
        logger.info(_WORKTREE_MATERIALIZED_EVENT, slug=slug, remote_sha=remote_sha)
        return

    local_sha = _resolve_branch_sha(repo, slug)
    if not _is_ancestor(repo, local_sha, remote_ref):
        raise WorktreeBranchDiverged(slug, local_sha, remote_sha)
    if local_sha != remote_sha:
        repo.git.update_ref(local_branch_ref, remote_sha, local_sha)
        logger.info(_WORKTREE_FAST_FORWARD_EVENT, slug=slug, old_sha=local_sha, new_sha=remote_sha)
    repo.git.worktree(_GIT_ADD, str(worktree_path), slug)


def _has_local_branch(repo: Repo, slug: str) -> bool:
    """Return whether the local repository has a branch with this todo slug."""
    return any(head.name == slug for head in repo.heads)


def _resolve_branch_sha(repo: Repo, branch: str) -> str:
    """Resolve a local branch tip."""
    result: str = repo.git.rev_parse(_LOCAL_BRANCH_REF_TEMPLATE.format(branch=branch)).strip()
    return result


def _resolve_ref_sha(repo: Repo, ref: str) -> str:
    """Resolve a git ref tip."""
    result: str = repo.git.rev_parse(ref).strip()
    return result


def _resolve_head_sha(worktree_path: Path) -> str:
    """Resolve the new worktree's HEAD."""
    return _resolve_ref_sha(Repo(str(worktree_path)), _GIT_HEAD_REF)


def _is_ancestor(repo: Repo, ancestor: str, descendant: str) -> bool:
    """Return whether ancestor is reachable from descendant."""
    try:
        repo.git.merge_base(_GIT_IS_ANCESTOR, ancestor, descendant)
    except GitCommandError as exc:
        if exc.status == 1:
            return False
        raise
    return True


def ensure_worktree_with_policy(cwd: str, slug: str, *, build_start_sha: str = _EMPTY_SHA) -> EnsureWorktreeResult:
    """Ensure worktree exists and run prep only when policy says it's stale."""
    created = _create_or_attach_worktree(cwd, slug, build_start_sha=build_start_sha)
    worktree_root = Path(cwd) / WORKTREE_DIR / slug
    add_worktree_trust(Path(cwd), worktree_root)
    try:
        schema_link = converge_project_schema_link(worktree_root)
    except (GitCommandError, OSError):
        # The schema association is advisory, so a failed link does not invalidate the worktree.
        logger.exception(
            _WORKTREE_SCHEMA_LINK_FAILED_EVENT,
            slug=slug,
            project_root=str(worktree_root),
        )
    else:
        logger.info(
            _WORKTREE_SCHEMA_LINK_EVENT,
            slug=slug,
            project_root=str(worktree_root),
            disposition=schema_link.disposition,
            resolved_target=str(schema_link.resolved_target) if schema_link.resolved_target is not None else None,
        )
    ensure_worktree_home(Path(cwd), slug)
    prep_decision = _decide_worktree_prep(cwd, slug, created=created)
    if prep_decision.should_prepare:
        _prepare_worktree(cwd, slug)
        _write_worktree_prep_state(cwd, slug, prep_decision.inputs_digest)
        return EnsureWorktreeResult(created=created, prepared=True, prep_reason=prep_decision.reason)
    return EnsureWorktreeResult(created=created, prepared=False, prep_reason=prep_decision.reason)


async def ensure_worktree_with_policy_async(
    cwd: str, slug: str, *, build_start_sha: str = _EMPTY_SHA
) -> EnsureWorktreeResult:
    """Async wrapper to ensure worktree with prep decision policy."""
    return await asyncio.to_thread(ensure_worktree_with_policy, cwd, slug, build_start_sha=build_start_sha)


def _prepare_worktree(cwd: str, slug: str) -> None:
    """Prepare a worktree using repo conventions.

    Conventions:
    - If `scripts.worktree:prepare` is defined in teleclaude.yml, run it.
    - Else if tools/worktree-prepare.sh exists and is executable, run it with the slug.
    - If Makefile has `install`, run `make install`.
    - Else if package.json exists, run `pnpm install` if available, otherwise `npm install`.
    - If neither applies, do nothing.
    """
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    worktree_prepare_script = Path(cwd) / "tools" / "worktree-prepare.sh"
    makefile = worktree_path / "Makefile"
    package_json = worktree_path / "package.json"

    def _has_make_target(target: str) -> bool:
        try:
            content = makefile.read_text(encoding="utf-8")
        except OSError:
            return False
        return re.search(rf"^{re.escape(target)}\s*:", content, re.MULTILINE) is not None

    if worktree_prepare_script.exists() and os.access(worktree_prepare_script, os.X_OK):
        cmd = [str(worktree_prepare_script), slug]
        logger.info("Preparing worktree with: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                cwd=str(Path(cwd)),
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {e.stdout or ''}\n"
                f"stderr: {e.stderr or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

    if makefile.exists() and _has_make_target("install"):
        logger.info("Preparing worktree with: make install")
        try:
            subprocess.run(
                ["make", "install"],
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: make install\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {e.stdout or ''}\n"
                f"stderr: {e.stderr or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

    if package_json.exists():
        use_pnpm = False
        if (worktree_path / "pnpm-lock.yaml").exists():
            use_pnpm = True
        else:
            use_pnpm = shutil.which("pnpm") is not None
        cmd = ["pnpm", "install"] if use_pnpm else ["npm", "install"]
        logger.info("Preparing worktree with: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {e.stdout or ''}\n"
                f"stderr: {e.stderr or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

    logger.info("No worktree preparation targets found for %s", slug)


__all__ = [
    "ensure_worktree_with_policy",
    "ensure_worktree_with_policy_async",
]
