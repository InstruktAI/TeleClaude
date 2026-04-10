"""Scaffold todo folders with canonical TeleClaude artifacts."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.models import JsonDict
from teleclaude.core.next_machine._types import StateValue
from teleclaude.session_identity import get_session_id as _get_session_id
from teleclaude.slug import validate_slug
from teleclaude.types.todos import DorState, TodoState

_DEFAULT_STATE = TodoState(dor=DorState(status="needs_work", score=0)).model_dump(exclude_none=True)

_BUG_STATE = TodoState(kind="bug").model_dump(exclude_none=True)


def _templates_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "todos"


def _read_template(name: str) -> str:
    template_path = _templates_root() / name
    return template_path.read_text(encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_todo_skeleton(  # pylint: disable=too-many-locals,unused-argument
    project_root: Path,
    slug: str,
    *,
    after: list[str] | None = None,
    group: str | None = None,
    seed_input: str | None = None,
) -> Path:
    """Create or refresh a todo skeleton folder.

    Creates:
    - todos/{slug}/requirements.md
    - todos/{slug}/implementation-plan.md
    - todos/{slug}/quality-checklist.md
    - todos/{slug}/state.yaml

    Optionally registers the slug in todos/roadmap.yaml when ``after`` or ``group`` is provided.
    When ``seed_input`` is provided, writes it as the initial content of ``input.md`` instead
    of the blank template.
    """
    validate_slug(slug)
    slug = slug.strip()

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug
    if todo_dir.exists():
        raise ValueError(f"Todo '{slug}' already exists at {todo_dir}")

    req = _read_template("requirements.md").format(slug=slug)
    plan = _read_template("implementation-plan.md").format(slug=slug)
    checklist = _read_template("quality-checklist.md").format(slug=slug)
    input_md = seed_input if seed_input is not None else _read_template("input.md").format(slug=slug)
    state_content = yaml.dump(_DEFAULT_STATE, default_flow_style=False, sort_keys=False)

    _write_file(todo_dir / "requirements.md", req)
    _write_file(todo_dir / "implementation-plan.md", plan)
    _write_file(todo_dir / "quality-checklist.md", checklist)
    _write_file(todo_dir / "input.md", input_md)
    _write_file(todo_dir / "state.yaml", state_content)

    return todo_dir


def create_bug_skeleton(  # pylint: disable=too-many-arguments
    project_root: Path,
    slug: str,
    description: str,
    *,
    body: str = "",
    reporter: str = "manual",
    session_id: str = "none",
) -> Path:
    """Create a bug todo skeleton folder.

    Creates:
    - todos/{slug}/bug.md
    - todos/{slug}/state.yaml

    Bug todos skip the prepare phase and start as pending build work.
    """
    validate_slug(slug)
    slug = slug.strip()

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug
    if todo_dir.exists():
        raise ValueError(f"Bug todo '{slug}' already exists at {todo_dir}")

    date = datetime.now(UTC).strftime("%Y-%m-%d")

    bug_md = _read_template("bug.md").format(
        description=description,
        body=body or "<!-- No additional detail provided -->",
        reporter=reporter,
        session_id=session_id,
        date=date,
    )
    state_content = yaml.dump(_BUG_STATE, default_flow_style=False, sort_keys=False)

    _write_file(todo_dir / "bug.md", bug_md)
    _write_file(todo_dir / "state.yaml", state_content)

    return todo_dir


def _emit_prepare_event(event_type: str, payload: JsonDict) -> None:
    """Fire-and-forget prepare lifecycle event (mirrors core helper)."""
    from teleclaude.core.next_machine.core import (  # pylint: disable=import-outside-toplevel
        _emit_prepare_event as _core_emit,
    )

    _core_emit(event_type, payload)  # type: ignore[arg-type]


def _inherit_parent_phase(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    project_root: Path,
    parent_slug: str,
    child_slug: str,
    child_dir: Path,
    parent_req_review: dict[str, StateValue],
    parent_plan_review: dict[str, StateValue],
    req_approved: bool,
    plan_approved: bool,
    parent_requirements_path: Path,
    parent_plan_path: Path,
) -> None:
    """Apply parent approved phase inheritance to a child todo (R10, R11)."""
    from teleclaude.core.next_machine.core import (  # pylint: disable=import-outside-toplevel
        read_phase_state,
        write_phase_state,
    )

    now = datetime.now(UTC).isoformat()
    child_state = read_phase_state(str(project_root), child_slug)

    # Determine inherited phase and skipped phases
    if plan_approved:
        inherited_phase = "prepared"
        skipped_phases = [
            "input_assessment",
            "triangulation",
            "requirements_review",
            "plan_drafting",
            "plan_review",
            "gate",
        ]
    else:
        # req_approved only
        inherited_phase = "plan_drafting"
        skipped_phases = ["input_assessment", "triangulation", "requirements_review"]

    # Copy parent artifacts
    if req_approved and parent_requirements_path.exists():
        (child_dir / "requirements.md").write_text(
            parent_requirements_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    if plan_approved and parent_plan_path.exists():
        (child_dir / "implementation-plan.md").write_text(
            parent_plan_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Set inherited verdicts
    if req_approved:
        child_state["requirements_review"] = dict(parent_req_review)
    if plan_approved:
        child_state["plan_review"] = dict(parent_plan_review)

    # Set phase
    child_state["current"] = inherited_phase

    # Record skipped audit entries
    audit = child_state.get("audit")
    if not isinstance(audit, dict):
        audit = {}
        child_state["audit"] = audit
    for phase in skipped_phases:
        audit[phase] = {"status": "skipped", "reason": "inherited_from_parent", "skipped_at": now}

    write_phase_state(str(project_root), child_slug, child_state)

    # Emit split_inherited event (R11)
    _emit_prepare_event(
        "domain.software-development.prepare.split_inherited",
        {"parent_slug": parent_slug, "child_slug": child_slug, "inherited_phase": inherited_phase},
    )
    # Emit phase_skipped per skipped phase
    for phase in skipped_phases:
        _emit_prepare_event(
            "domain.software-development.prepare.phase_skipped",
            {"slug": child_slug, "phase": phase, "reason": "inherited_from_parent"},
        )


def split_todo(project_root: Path, parent_slug: str, child_slugs: list[str]) -> list[Path]:  # pylint: disable=too-many-locals
    """Split a todo into child items (container transition).

    Scaffolds children, cleans parent builder artifacts, and sets container state.
    Returns list of created child directories.

    Raises:
        FileNotFoundError: If parent todo directory does not exist
        ValueError: If parent is already a container or child slug is invalid
        FileExistsError: If any child directory already exists
    """
    from teleclaude.core.next_machine.core import (  # pylint: disable=import-outside-toplevel
        read_phase_state,
        write_phase_state,
    )

    validate_slug(parent_slug)
    parent_slug = parent_slug.strip()

    todos_root = project_root / "todos"
    parent_dir = todos_root / parent_slug

    if not parent_dir.exists():
        raise FileNotFoundError(f"Todo '{parent_slug}' not found at {parent_dir}")

    # Check parent is not already a container
    state = read_phase_state(str(project_root), parent_slug)
    breakdown = state.get("breakdown", {})
    if isinstance(breakdown, dict) and breakdown.get("todos"):
        raise ValueError(f"Todo '{parent_slug}' is already a container with children: {breakdown['todos']}")

    # Validate all child slugs and check they don't exist
    for child in child_slugs:
        validate_slug(child)
        child_dir = todos_root / child
        if child_dir.exists():
            raise FileExistsError(f"Child todo '{child}' already exists at {child_dir}")

    # Read parent input.md to seed children with context
    parent_input_path = parent_dir / "input.md"
    parent_input_content: str | None = None
    if parent_input_path.exists():
        parent_input_content = parent_input_path.read_text(encoding="utf-8")

    # Determine parent's highest approved phase for inheritance (R10)
    parent_req_review = state.get("requirements_review", {})
    parent_plan_review = state.get("plan_review", {})
    req_approved = isinstance(parent_req_review, dict) and parent_req_review.get("verdict") == "approve"
    plan_approved = isinstance(parent_plan_review, dict) and parent_plan_review.get("verdict") == "approve"

    parent_requirements_path = parent_dir / "requirements.md"
    parent_plan_path = parent_dir / "implementation-plan.md"

    # Scaffold children — grouped under parent, seeded with parent context
    created: list[Path] = []
    for child in child_slugs:
        child_dir = create_todo_skeleton(
            project_root,
            child,
            group=parent_slug,
            seed_input=parent_input_content,
        )
        created.append(child_dir)

        # Inherit parent approved phase if applicable (R10, R11)
        if req_approved or plan_approved:
            _inherit_parent_phase(
                project_root=project_root,
                parent_slug=parent_slug,
                child_slug=child,
                child_dir=child_dir,
                parent_req_review=parent_req_review if isinstance(parent_req_review, dict) else {},
                parent_plan_review=parent_plan_review if isinstance(parent_plan_review, dict) else {},
                req_approved=req_approved,
                plan_approved=plan_approved,
                parent_requirements_path=parent_requirements_path,
                parent_plan_path=parent_plan_path,
            )

    # Clean parent builder artifacts — keep only input.md and state.yaml
    keep = {"input.md", "state.yaml"}
    for f in parent_dir.iterdir():
        if f.is_file() and f.name not in keep:
            f.unlink()

    # Reset parent state.yaml to container state
    state["breakdown"] = {"assessed": True, "todos": child_slugs}  # type: ignore[dict-item]
    state["dor"] = {
        "score": 0,
        "status": "needs_work",
        "schema_version": 1,
        "blockers": [],
        "actions_taken": [],
    }
    state["requirements_review"] = {
        "verdict": "",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
    }
    state["plan_review"] = {
        "verdict": "",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
    }
    state["grounding"] = {
        "valid": False,
        "base_sha": "",
        "input_digest": "",
        "referenced_paths": [],
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    }
    state["current"] = "input_assessment"
    write_phase_state(str(project_root), parent_slug, state)

    return created


def remove_todo(project_root: Path, slug: str) -> None:  # pylint: disable=too-many-locals
    """Remove a todo and all its references. Best-effort: removes whatever exists.

    Removes worktree and local branch for the given slug. DB cleanup
    (roadmap, icebox, state, artifacts) is handled by the /todos/remove API route.

    Args:
        project_root: Project root directory
        slug: Todo slug to remove

    Raises:
        ValueError: If slug format is invalid
    """
    from teleclaude.git import GitCommandError, Repo  # pylint: disable=import-outside-toplevel

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


def _clean_main_working_tree(  # pylint: disable=too-many-branches
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
        except Exception:  # pylint: disable=broad-exception-caught
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
        except Exception:  # pylint: disable=broad-exception-caught
            pass


_scaffold_logger = get_logger(__name__)


def _collect_session_touched_files(project_path: str) -> set[str]:  # pylint: disable=too-many-locals
    """Extract files touched by the current agent session from its transcript.

    Uses the same transcript parsing as the checkpoint system to determine
    which files this session actually mutated. Codex sessions aggregate the
    parent transcript plus any descendant subagent transcripts so attribution
    matches the effective work owned by the parent session.

    Raises:
        ValueError: If session ID is missing, transcript is unavailable,
            or no touched files can be determined.
    """
    from sqlmodel import Session as SqlSession  # pylint: disable=import-outside-toplevel

    from teleclaude.core import db_models  # pylint: disable=import-outside-toplevel
    from teleclaude.core.agents import AgentName, get_default_agent  # pylint: disable=import-outside-toplevel
    from teleclaude.core.codex_transcript import (  # pylint: disable=import-outside-toplevel
        discover_codex_transcript_path,
        discover_current_codex_transcript_path,
    )
    from teleclaude.hooks.checkpoint._git import _extract_turn_file_signals  # pylint: disable=import-outside-toplevel
    from teleclaude.hooks.receiver._session import _create_sync_engine  # pylint: disable=import-outside-toplevel
    from teleclaude.utils.transcript import extract_effective_tool_calls  # pylint: disable=import-outside-toplevel

    session_id = _get_session_id()
    if not session_id:
        raise ValueError("from-main requires an active agent session ($TMPDIR/teleclaude_identity.json not found)")

    with SqlSession(_create_sync_engine()) as db_session:
        row = db_session.get(db_models.Session, session_id)

    if not row:
        raise ValueError(f"Session {session_id} not found in database")

    try:
        agent_name = AgentName.from_str(getattr(row, "active_agent", None) or get_default_agent())
    except ValueError:
        agent_name = AgentName.CLAUDE

    transcript_candidates: list[str] = []
    native_log_file = getattr(row, "native_log_file", None)
    native_session_id = getattr(row, "native_session_id", None)
    if native_log_file:
        transcript_candidates.append(native_log_file)
    if not transcript_candidates and agent_name == AgentName.CODEX and native_session_id:
        discovered_path = discover_codex_transcript_path(native_session_id)
        if discovered_path:
            transcript_candidates.append(discovered_path)
    if not transcript_candidates:
        raise ValueError(f"No transcript found for session {session_id}")

    if agent_name == AgentName.CODEX:
        current_transcript_path = discover_current_codex_transcript_path()
        if current_transcript_path and current_transcript_path not in transcript_candidates:
            transcript_candidates.insert(0, current_transcript_path)

    attempted_transcripts: list[str] = []
    for transcript_path in transcript_candidates:
        attempted_transcripts.append(transcript_path)
        timeline = extract_effective_tool_calls(
            transcript_path,
            agent_name,
            native_session_id=native_session_id,
            scope="session",
        )
        touched_files, _saw_mutation = _extract_turn_file_signals(timeline, project_path)

        if touched_files:
            _scaffold_logger.debug(
                "Session %s touched %d files: %s", session_id, len(touched_files), sorted(touched_files)
            )
            return touched_files

    attempted = ", ".join(attempted_transcripts) if attempted_transcripts else "<none>"
    raise ValueError(
        f"Could not determine session-touched files from transcript.\n"
        f"Session: {session_id}, attempted transcripts: {attempted}"
    )


def create_from_main_skeleton(  # pylint: disable=too-many-locals,too-many-statements
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
    from teleclaude.core.next_machine.slug_resolution import set_item_phase  # pylint: disable=import-outside-toplevel
    from teleclaude.core.next_machine.state_io import mark_phase  # pylint: disable=import-outside-toplevel
    from teleclaude.core.next_machine.worktrees import (  # pylint: disable=import-outside-toplevel
        _create_or_attach_worktree,
        _decide_worktree_prep,
        _prepare_worktree,
        _write_worktree_prep_state,
    )
    from teleclaude.git import InvalidGitRepositoryError, Repo  # pylint: disable=import-outside-toplevel

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

    # --- 5c. Scaffold todo artifacts ---
    project_root = Path(cwd)
    todo_dir = create_todo_skeleton(project_root, slug)

    # Overwrite all artifacts with from-main markers.
    # The human authored these changes directly — build gates and reviewers
    # recognize the marker and handle accordingly.
    from_main_marker = "<!-- from-main: inline work delivered under human supervision -->"
    desc_text = description or "See diff for details."

    _write_file(todo_dir / "requirements.md", f"{from_main_marker}\n# Requirements: {slug}\n\n{desc_text}\n")
    _write_file(todo_dir / "implementation-plan.md", f"{from_main_marker}\n# Implementation Plan: {slug}\n")
    _write_file(todo_dir / "quality-checklist.md", f"{from_main_marker}\n# Quality Checklist: {slug}\n")

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

    # --- 5g. Ensure roadmap entry exists (write_state requires slug→UUID resolution) ---
    worktree_cwd = str(worktree_path)
    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    _from_main_db = _get_todos_db_sync(worktree_cwd)
    _from_main_conn = _from_main_db._sync_conn()  # pylint: disable=protected-access
    try:
        import uuid as _uuid  # pylint: disable=import-outside-toplevel

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

    # --- 5h. Write DB artifacts (mark_phase "prepared" validates their existence) ---
    _art_db = _get_todos_db_sync(worktree_cwd)
    _art_conn = _art_db._sync_conn()  # pylint: disable=protected-access
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
                _art_conn.execute(
                    "INSERT OR REPLACE INTO todo_artifacts (id, slug, name, content, updated_at) "  # guard: raw-sql
                    "VALUES (?, ?, ?, ?, datetime('now'))",
                    (_art_id, slug, _art_name, _art_content),
                )
            _art_conn.commit()
    finally:
        _art_conn.close()

    # --- 5i. Set state for review dispatch (before cleaning main — atomic) ---
    set_item_phase(worktree_cwd, slug, "in_progress")
    mark_phase(worktree_cwd, slug, "prepared")
    mark_phase(worktree_cwd, slug, "build_complete")

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
        f"the worktree at {WORKTREE_DIR}/{slug}/. The main branch is off-limits.\n"
        "\n"
        "Next steps:\n"
        f'  1. git -C {WORKTREE_DIR}/{slug} add -A && git -C {WORKTREE_DIR}/{slug} commit -m "your commit message"\n'
        f"  2. telec sessions run --command /next-work --args {slug}"
        f" --agent <agent> --mode med --detach  (choose a fitting agent)"
    )
