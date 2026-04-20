"""Todo scaffolding: worktree-based todo creation from uncommitted main changes."""

from __future__ import annotations

import hashlib as _hashlib
import shutil
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - narrow sync lookup must tolerate pre-migration local DBs
from sqlmodel import Session as SqlSession

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.codex_transcript import discover_codex_transcript_path, discover_current_codex_transcript_path
from teleclaude.core.next_machine.slug_resolution import set_item_phase
from teleclaude.core.next_machine.state_io import _get_todos_db_sync, apply_prepared_state
from teleclaude.core.next_machine.worktrees import (
    _create_or_attach_worktree,
    _decide_worktree_prep,
    _prepare_worktree,
    _write_worktree_prep_state,
)
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, Repo
from teleclaude.hooks.receiver._session import _create_sync_engine
from teleclaude.session_identity import get_session_id as _get_session_id
from teleclaude.session_scoping import resolve_scoped_paths
from teleclaude.slug import validate_slug


class TranscriptUnavailable(ValueError):
    """Raised when a session has no resolvable transcript to scope changes from.

    Subclass of ValueError so legacy callers catching ValueError still work, while
    allowing precise routing (e.g. scoped-gate fallback to git status) via an
    explicit except clause instead of string-matching the formatted message.
    """


class NoSessionTouchedFiles(ValueError):
    """Raised when session scoping succeeds but owns no transferable paths."""


def remove_todo(project_root: Path, slug: str) -> None:
    """Remove a todo and all its references. Best-effort: removes whatever exists.

    Removes worktree and local branch for the given slug. DB cleanup
    (roadmap, icebox, state, artifacts) is handled by the /todos/remove API route.

    Args:
        project_root: Project root directory
        slug: Todo slug to remove

    Raises:
        ValueError: If slug format is invalid
    """
    validate_slug(slug)
    slug = slug.strip()

    worktree_path = project_root / WORKTREE_DIR / slug
    repo = Repo(str(project_root))
    if worktree_path.exists():
        try:
            repo.git.worktree("remove", "--force", str(worktree_path))
        except GitCommandError:
            pass

    try:
        repo.git.branch("-D", slug)
    except GitCommandError:
        pass


def _classify_porcelain_status(
    status_output: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Classify git porcelain status lines into modified, untracked, deleted, added."""
    modified: list[str] = []
    untracked: list[str] = []
    deleted: list[str] = []
    added: list[str] = []
    for line in status_output.rstrip().splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        filepath = line[3:].strip()
        if " -> " in filepath:
            filepath = filepath.split(" -> ", 1)[1]
        if code == "??":
            untracked.append(filepath)
        elif code.strip().startswith("D"):
            deleted.append(filepath)
        elif code == "A ":
            added.append(filepath)
        else:
            modified.append(filepath)
    return modified, untracked, deleted, added


def _transfer_files_to_worktree(
    project_root: Path,
    worktree_path: Path,
    modified: list[str],
    untracked: list[str],
    deleted: list[str],
) -> None:
    """Copy changed files from main to worktree and remove deleted files."""
    for filepath in modified + untracked:
        src = project_root / filepath
        dst = worktree_path / filepath
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    for filepath in deleted:
        dst = worktree_path / filepath
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()


def _clean_main_working_tree(
    repo: Any,
    project_root: Path,
    modified: list[str],
    untracked: list[str],
    added: list[str] | None = None,
) -> None:
    """Restore tracked files from HEAD, remove untracked/added files, and unstage."""
    if modified:
        try:
            repo.git.checkout("HEAD", "--", *modified)
        except Exception:
            pass

    # Added files don't exist at HEAD — delete from disk and unstage
    for filepath in added or []:
        src = project_root / filepath
        if src.exists():
            if src.is_dir():
                shutil.rmtree(src)
            else:
                src.unlink()
            parent = src.parent
            while parent != project_root and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent

    for filepath in untracked:
        src = project_root / filepath
        if not src.exists():
            continue
        if src.is_dir():
            shutil.rmtree(src)
        else:
            src.unlink()
        parent = src.parent
        while parent != project_root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    # Unstage all transferred files explicitly using pathspec reset
    all_files = list(modified) + list(untracked) + list(added or [])
    if all_files:
        try:
            repo.git.reset("HEAD", "--", *all_files)
        except Exception:
            pass


_scaffold_logger = get_logger(__name__)


def _load_session_transcript_metadata(session_id: str) -> tuple[str | None, str | None, str | None]:
    """Load the minimal session metadata needed to discover transcript files.

    Uses raw SQL projected to the three columns the transcript discovery needs
    so the lookup keeps working against local session DBs that have not yet
    applied newer schema migrations.
    """

    with SqlSession(_create_sync_engine()) as db_session:
        row = db_session.exec(  # type: ignore[call-overload]
            text(
                "SELECT active_agent, native_log_file, native_session_id "  # guard: raw-sql
                "FROM sessions WHERE session_id = :session_id"
            ).bindparams(session_id=session_id)
        ).first()
        try:
            active_agent_raw, native_log_file_raw, native_session_id_raw = row
        except (TypeError, ValueError):
            fallback_row = db_session.get(db_models.Session, session_id)
            if not fallback_row:
                raise ValueError(f"Session {session_id} not found in database") from None
            active_agent_raw = getattr(fallback_row, "active_agent", None)
            native_log_file_raw = getattr(fallback_row, "native_log_file", None)
            native_session_id_raw = getattr(fallback_row, "native_session_id", None)

    return (
        str(active_agent_raw) if active_agent_raw else None,
        str(native_log_file_raw) if native_log_file_raw else None,
        str(native_session_id_raw) if native_session_id_raw else None,
    )


def _collect_session_touched_files(project_path: str) -> set[str]:
    """Extract files touched by the current agent session from its transcript.

    Uses the same transcript parsing as the checkpoint system to determine
    which files this session actually mutated. Codex sessions aggregate the
    parent transcript plus any descendant subagent transcripts so attribution
    matches the effective work owned by the parent session.

    Raises:
        ValueError: If session ID is missing, transcript is unavailable,
            or no touched files can be determined.
    """
    session_id = _get_session_id()
    if not session_id:
        raise ValueError("from-main requires an active agent session ($TMPDIR/teleclaude_identity.json not found)")

    active_agent_raw, native_log_file, native_session_id = _load_session_transcript_metadata(session_id)
    try:
        agent_name = AgentName.from_str(str(active_agent_raw) if active_agent_raw else get_default_agent())
    except ValueError:
        agent_name = AgentName.CLAUDE

    transcript_path = native_log_file
    if agent_name == AgentName.CODEX:
        current_transcript_path = discover_current_codex_transcript_path()
        if current_transcript_path:
            transcript_path = current_transcript_path
        elif not transcript_path and native_session_id:
            transcript_path = discover_codex_transcript_path(native_session_id)

    if not transcript_path and agent_name != AgentName.CODEX:
        raise TranscriptUnavailable(f"No transcript found for session {session_id}")
    if not transcript_path and not native_session_id:
        raise TranscriptUnavailable(f"No transcript found for session {session_id}")

    scoped_paths = resolve_scoped_paths(
        session_id=session_id,
        workspace_root=project_path,
        agent_name=agent_name.value,
        scope_mode="session_dirty",
        transcript_path=transcript_path,
        native_session_id=native_session_id,
    )

    if scoped_paths.paths:
        touched_files = set(scoped_paths.paths)
        _scaffold_logger.debug("Session %s touched %d files: %s", session_id, len(touched_files), sorted(touched_files))
        return touched_files

    raise NoSessionTouchedFiles(
        f"Could not determine session-touched files from transcript.\n"
        f"Session: {session_id}, attempted transcript: {transcript_path or '<none>'}"
    )


def create_from_main_skeleton(
    cwd: str,
    slug: str,
    *,
    description: str | None = None,
    all_files: bool = False,
) -> str:
    """Transfer uncommitted changes from main into a todo worktree for review.

    File scoping is automatic: the session transcript is parsed to determine
    which files this agent session actually touched. Only those files are
    transferred. Requires an active agent session ($TMPDIR/teleclaude_identity.json).

    Steps:
    1. Validate preconditions (on main, has uncommitted changes)
    2. Capture change metadata
    3. Scaffold todo artifacts
    4. Push scaffold to remote
    5. Create worktree
    6. Transfer files to worktree
    7. Clean main working tree
    8. Set state for review dispatch

    Returns:
        Human-readable status output with next-step instructions.

    Raises:
        ValueError: If not on main or no uncommitted changes
        RuntimeError: If scaffold push or worktree creation fails
    """

    # --- 5a. Validate preconditions ---
    validate_slug(slug)
    slug = slug.strip()

    try:
        repo = Repo(cwd)
    except InvalidGitRepositoryError as exc:
        raise ValueError(f"Not a git repository: {cwd}") from exc

    branch = repo.active_branch.name
    if branch != "main":
        raise ValueError(f"from-main requires being on the main branch. Current branch: {branch}")

    status_output = repo.git.status("--porcelain")
    if not status_output.strip():
        raise ValueError("No uncommitted changes on main. Nothing to transfer.")

    # --- 5b. Capture uncommitted changes ---
    modified_files, untracked_files, deleted_files, added_files = _classify_porcelain_status(status_output)

    # Scope to files this session actually touched (transcript-based), unless --all
    if not all_files:
        session_files = _collect_session_touched_files(cwd)
        modified_files = [f for f in modified_files if f in session_files]
        untracked_files = [f for f in untracked_files if f in session_files]
        deleted_files = [f for f in deleted_files if f in session_files]
        added_files = [f for f in added_files if f in session_files]

    all_changed = modified_files + untracked_files + deleted_files + added_files
    if not all_changed:
        raise ValueError("No uncommitted changes to transfer.")

    # --- 5c. Prepare artifact content (DB-only, no filesystem scaffold) ---
    project_root = Path(cwd)
    from_main_marker = "<!-- from-main: inline work delivered under human supervision -->"
    desc_text = description or "See diff for details."

    # --- 5d. Create worktree ---
    created = _create_or_attach_worktree(cwd, slug)
    worktree_path = project_root / WORKTREE_DIR / slug

    # Run prep if needed
    prep_decision = _decide_worktree_prep(cwd, slug, created=created)
    if prep_decision.should_prepare:
        _prepare_worktree(cwd, slug)
        _write_worktree_prep_state(cwd, slug, prep_decision.inputs_digest)

    # --- 5f. Transfer changes to worktree ---
    _transfer_files_to_worktree(
        project_root, worktree_path, modified_files + added_files, untracked_files, deleted_files
    )

    # Commit the worktree handoff before cleaning main so a hook failure leaves
    # the human's original checkout untouched for manual recovery.
    wt_repo = Repo(str(worktree_path))
    wt_repo.git.add("-A")
    wt_repo.git.commit("-m", f"chore({slug}): from-main handoff")

    # --- 5g. Ensure roadmap entry exists (write_state requires slug→UUID resolution) ---
    worktree_cwd = str(worktree_path)

    _from_main_db = _get_todos_db_sync(worktree_cwd)
    _from_main_conn = _from_main_db._sync_conn()
    try:
        _existing = _from_main_conn.execute(
            "SELECT 1 FROM roadmap WHERE slug = ? AND status != 'delivered'",  # guard: raw-sql
            (slug,),
        ).fetchone()
        if not _existing:
            _now = datetime.now(UTC).isoformat()
            _max_pos = _from_main_conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM roadmap",  # guard: raw-sql
            ).fetchone()[0]
            _from_main_conn.execute(
                "INSERT INTO roadmap "  # guard: raw-sql
                "(id, slug, position, description, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (str(_uuid.uuid4()), slug, _max_pos, description, _now, _now),
            )
            _from_main_conn.commit()
    finally:
        _from_main_conn.close()

    # --- 5h. Write DB artifacts (apply_prepared_state validates their existence) ---
    _art_db = _get_todos_db_sync(worktree_cwd)
    _art_conn = _art_db._sync_conn()
    try:
        _art_id_row = _art_conn.execute(
            "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
        if _art_id_row:
            _art_id = _art_id_row[0]
            for _art_name, _art_content in [
                ("requirements", f"{from_main_marker}\n# Requirements: {slug}\n\n{desc_text}\n"),
                ("implementation-plan", f"{from_main_marker}\n# Implementation Plan: {slug}\n"),
                ("quality-checklist", f"{from_main_marker}\n# Quality Checklist: {slug}\n"),
            ]:
                _art_digest = _hashlib.sha256(_art_content.encode("utf-8")).hexdigest()
                _art_conn.execute(
                    "INSERT OR REPLACE INTO todo_artifacts "  # guard: raw-sql
                    "(id, slug, name, content, digest, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    (_art_id, slug, _art_name, _art_content, _art_digest),
                )
            _art_conn.commit()
    finally:
        _art_conn.close()

    # --- 5i. Set state for review dispatch (before cleaning main — atomic) ---
    # apply_prepared_state stamps DOR, grounding baseline, and prepare review
    # verdicts so derive_prepare_phase resolves to PREPARED. The build handoff
    # commit above means derive_work_phase resolves to BUILD_COMPLETE naturally.
    set_item_phase(worktree_cwd, slug, "in_progress")
    apply_prepared_state(worktree_cwd, slug)

    # --- 5h. Clean main working tree (only after all worktree operations succeed) ---
    _clean_main_working_tree(repo, project_root, modified_files, untracked_files, added_files)

    # --- 5i. Return instructions ---
    return (
        f"Todo created: {slug}\n"
        f"Worktree: {WORKTREE_DIR}/{slug}/\n"
        "\n"
        "IMPORTANT: Your uncommitted changes have been transferred to the worktree.\n"
        "The repo root main branch has been cleaned. Do NOT commit, push, or sync\n"
        "any files back to the main branch. All work happens exclusively inside\n"
        f"the worktree at {WORKTREE_DIR}/{slug}/. The main branch is off-limits."
    )
