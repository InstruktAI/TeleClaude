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

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    EnsureWorktreeResult,
    WorktreePrepDecision,
    _PREP_INPUT_FILES,
    _PREP_ROOT_INPUT_FILES,
    _PREP_STATE_VERSION,
    _WORKTREE_PREP_STATE_REL,
)
from teleclaude.core.next_machine.state_io import _file_sha256

logger = get_logger(__name__)


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
    except (json.JSONDecodeError, OSError):
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


def _create_or_attach_worktree(cwd: str, slug: str) -> bool:
    """Ensure the slug worktree path exists by creating or reattaching its branch."""
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
        # Fetch latest main and branch from origin/main (not local HEAD)
        repo.git.fetch("origin", "main")
        repo.git.worktree("add", str(worktree_path), "-b", slug, "origin/main")
    except GitCommandError as exc:
        branch_exists = any(head.name == slug for head in repo.heads)
        if not branch_exists:
            logger.error(
                "Failed to create worktree for slug=%s cwd=%s worktree_path=%s branch_exists=%s: %s",
                slug,
                cwd,
                worktree_path,
                branch_exists,
                exc,
                exc_info=True,
            )
            raise
        try:
            repo.git.worktree("add", str(worktree_path), slug)
        except GitCommandError as attach_exc:
            logger.error(
                "Failed to create worktree for slug=%s cwd=%s worktree_path=%s branch_exists=%s: %s",
                slug,
                cwd,
                worktree_path,
                branch_exists,
                attach_exc,
                exc_info=True,
            )
            raise

    logger.info("Created worktree at %s", worktree_path)
    return True


def _ensure_todo_on_remote_main(cwd: str, slug: str) -> tuple[bool, str]:
    """Commit and push todo artifacts to origin/main.

    Worktrees are created from origin/main. Todo artifacts scaffolded locally
    (e.g. by ``telec bugs report`` or ``telec todo create``) must be committed
    and pushed so the worktree includes them. This is a hard prerequisite —
    if push fails, the caller must surface the error.

    Returns:
        Tuple of (action_taken, reason).
    """
    local_todo = Path(cwd) / "todos" / slug
    if not local_todo.exists() or not any(local_todo.iterdir()):
        return False, "no_local_artifacts"

    try:
        repo = Repo(cwd)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False, "not_a_repo"

    # Fetch to check against current remote state
    try:
        repo.git.fetch("origin", "main")
    except GitCommandError as exc:
        logger.warning("fetch origin main failed during todo remote sync: %s", exc)
        return False, "fetch_skipped"

    # Check if the todo folder already exists on origin/main
    try:
        output = repo.git.ls_tree("origin/main", "--", f"todos/{slug}")
        if output.strip():
            return False, "already_on_remote"
    except GitCommandError:
        pass  # ls-tree errors if path doesn't exist — means not on remote

    # Todo exists locally but not on remote — commit and push
    todo_rel = f"todos/{slug}"

    # Commit if there are uncommitted todo artifacts
    status_output = repo.git.status("--porcelain", "--", todo_rel)
    if status_output.strip():
        commit_paths = [todo_rel]
        # Include roadmap.yaml if dirty (may have been updated by auto-add)
        roadmap_status = repo.git.status("--porcelain", "--", "todos/roadmap.yaml")
        if roadmap_status.strip():
            commit_paths.append("todos/roadmap.yaml")

        msg = (
            f"chore(todos): scaffold {slug}\n\n"
            "Automated pre-worktree housekeeping: local todo artifacts must exist on\n"
            "origin/main before worktree creation so workers find them.\n\n"
            "\U0001f916 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
            "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
        )
        try:
            repo.git.add("--", *commit_paths)
            repo.git.commit("-m", msg, "--only", "--", *commit_paths)
        except GitCommandError as exc:
            logger.warning("Failed to commit todo artifacts for %s: %s", slug, exc)
            return False, "commit_skipped"

    # Push — try direct first, then reconcile with rebase if diverged
    try:
        repo.git.push("origin", "main")
        logger.info("Pushed todo artifacts for %s to origin/main", slug)
        return True, "committed_and_pushed"
    except GitCommandError:
        pass

    # Push failed (likely non-fast-forward) — try pull --rebase then push
    try:
        repo.git.pull("--rebase", "origin", "main")
        repo.git.push("origin", "main")
        logger.info("Rebased and pushed todo artifacts for %s to origin/main", slug)
        return True, "rebased_and_pushed"
    except GitCommandError as exc:
        # Abort rebase if it's stuck
        try:
            repo.git.rebase("--abort")
        except GitCommandError:
            pass
        logger.warning(
            "Could not push todo artifacts for %s to origin/main: %s",
            slug,
            exc,
        )
        return False, "push_deferred"


def ensure_worktree_with_policy(cwd: str, slug: str) -> EnsureWorktreeResult:
    """Ensure worktree exists and run prep only when policy says it's stale."""
    created = _create_or_attach_worktree(cwd, slug)
    prep_decision = _decide_worktree_prep(cwd, slug, created=created)
    if prep_decision.should_prepare:
        _prepare_worktree(cwd, slug)
        _write_worktree_prep_state(cwd, slug, prep_decision.inputs_digest)
        return EnsureWorktreeResult(created=created, prepared=True, prep_reason=prep_decision.reason)
    return EnsureWorktreeResult(created=created, prepared=False, prep_reason=prep_decision.reason)


async def ensure_worktree_with_policy_async(cwd: str, slug: str) -> EnsureWorktreeResult:
    """Async wrapper to ensure worktree with prep decision policy."""
    return await asyncio.to_thread(ensure_worktree_with_policy, cwd, slug)


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
