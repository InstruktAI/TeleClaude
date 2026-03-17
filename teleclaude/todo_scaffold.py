"""Scaffold todo folders with canonical TeleClaude artifacts."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.models import JsonDict
from teleclaude.core.next_machine._types import StateValue
from teleclaude.slug import validate_slug
from teleclaude.types.todos import BreakdownState, DorState, TodoState

_DEFAULT_STATE = TodoState(
    build="pending",
    review="pending",
    deferrals_processed=False,
    breakdown=BreakdownState(assessed=False, todos=[]),
    dor=DorState(status="needs_work", score=0),
    review_round=0,
    max_review_rounds=3,
    review_baseline_commit="",
    unresolved_findings=[],
    resolved_findings=[],
).model_dump()


_BUG_STATE = TodoState(
    kind="bug",
    build="pending",
    review="pending",
    deferrals_processed=False,
    breakdown=BreakdownState(assessed=False, todos=[]),
    dor=None,
    review_round=0,
    max_review_rounds=3,
    review_baseline_commit="",
    unresolved_findings=[],
    resolved_findings=[],
).model_dump()


def _templates_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "todos"


def _read_template(name: str) -> str:
    template_path = _templates_root() / name
    return template_path.read_text(encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_todo_skeleton(
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
    - todos/{slug}/demo.md
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
    demo_md = _read_template("demo.md").format(slug=slug)
    state_content = yaml.dump(_DEFAULT_STATE, default_flow_style=False, sort_keys=False)

    _write_file(todo_dir / "requirements.md", req)
    _write_file(todo_dir / "implementation-plan.md", plan)
    _write_file(todo_dir / "quality-checklist.md", checklist)
    _write_file(todo_dir / "input.md", input_md)
    _write_file(todo_dir / "demo.md", demo_md)
    _write_file(todo_dir / "state.yaml", state_content)

    if after is not None or group is not None:
        from teleclaude.core.next_machine.core import add_to_roadmap

        # Deduplicate and clean deps
        deduped: list[str] = []
        for item in after or []:
            cleaned = item.strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)

        add_to_roadmap(str(project_root), slug, after=deduped or None, group=group)

    return todo_dir


def create_bug_skeleton(
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
    from datetime import datetime

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
    from teleclaude.core.next_machine.core import _emit_prepare_event as _core_emit

    _core_emit(event_type, payload)  # type: ignore[arg-type]


def _inherit_parent_phase(
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
    from teleclaude.core.next_machine.core import read_phase_state, write_phase_state

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
    child_state["prepare_phase"] = inherited_phase

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


def split_todo(project_root: Path, parent_slug: str, child_slugs: list[str]) -> list[Path]:
    """Split a todo into child items (container transition).

    Scaffolds children, cleans parent builder artifacts, and sets container state.
    Returns list of created child directories.

    Raises:
        FileNotFoundError: If parent todo directory does not exist
        ValueError: If parent is already a container or child slug is invalid
        FileExistsError: If any child directory already exists
    """
    from teleclaude.core.next_machine.core import read_phase_state, write_phase_state

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
    state["prepare_phase"] = ""
    write_phase_state(str(project_root), parent_slug, state)

    return created


def remove_todo(project_root: Path, slug: str) -> None:
    """Remove a todo and all its references. Best-effort: removes whatever exists.

    Removes:
    - Worktree trees/{slug}/ (if present)
    - Local branch {slug} (if present)
    - todos/{slug}/ directory
    - Entry from todos/roadmap.yaml
    - Entry from todos/icebox.yaml (if present)
    - All `after` dependency references to this slug in roadmap and icebox

    Args:
        project_root: Project root directory
        slug: Todo slug to remove

    Raises:
        ValueError: If slug format is invalid
        FileNotFoundError: If slug has no artifacts anywhere (unknown slug)
    """
    from teleclaude.core.next_machine.core import (
        clean_dependency_references,
        remove_from_icebox,
        remove_from_roadmap,
    )

    validate_slug(slug)
    slug = slug.strip()

    # Remove worktree if present (best-effort: non-fatal)
    worktree_path = project_root / WORKTREE_DIR / slug
    found_worktree = worktree_path.exists()
    if found_worktree:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            capture_output=True,
            cwd=str(project_root),
        )

    # Remove local branch if present (best-effort: non-fatal)
    subprocess.run(
        ["git", "branch", "-D", slug],
        capture_output=True,
        cwd=str(project_root),
    )

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug
    icebox_dir = todos_root / "_icebox" / slug

    # Check both active and icebox locations
    found_in_active = todo_dir.exists()
    found_in_icebox_dir = icebox_dir.exists()
    found_directory = found_in_active or found_in_icebox_dir
    target_dir = todo_dir if found_in_active else icebox_dir

    found_in_roadmap = remove_from_roadmap(str(project_root), slug)
    found_in_icebox = remove_from_icebox(str(project_root), slug)

    # Clean up dependency references
    clean_dependency_references(str(project_root), slug)

    # Delete directory if it exists (from either location)
    if found_directory:
        shutil.rmtree(target_dir)

    # Error only if slug is completely unknown
    if not (found_directory or found_in_roadmap or found_in_icebox or found_worktree):
        raise FileNotFoundError(f"Todo '{slug}' not found in directory, roadmap, icebox, or worktree")


def _classify_porcelain_status(
    status_output: str,
) -> tuple[list[str], list[str], list[str]]:
    """Classify git porcelain status lines into modified, untracked, deleted."""
    modified: list[str] = []
    untracked: list[str] = []
    deleted: list[str] = []
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
        else:
            modified.append(filepath)
    return modified, untracked, deleted


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
) -> None:
    """Restore tracked files from HEAD and remove untracked files."""
    for filepath in modified:
        try:
            clean_content = repo.git.show(f"HEAD:{filepath}")
            src = project_root / filepath
            src.write_text(clean_content, encoding="utf-8")
        except Exception:
            pass

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

    try:
        repo.git.reset("HEAD")
    except Exception:
        pass


def _filter_by_paths(file_list: list[str], paths: list[str]) -> list[str]:
    """Filter file list to only include entries matching any of the given path prefixes."""
    return [f for f in file_list if any(f == p or f.startswith(p + "/") for p in paths)]


def create_from_main_skeleton(
    cwd: str,
    slug: str,
    *,
    description: str | None = None,
    paths: list[str] | None = None,
) -> str:
    """Transfer uncommitted changes from main into a todo worktree for review.

    Args:
        paths: Optional list of file paths to scope the transfer. When provided,
            only files matching these paths (exact or prefix) are transferred.
            Without this, ALL dirty files from git status are transferred.

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
    from git import Repo
    from git.exc import InvalidGitRepositoryError

    from teleclaude.core.next_machine.state_io import mark_phase, mark_ready
    from teleclaude.core.next_machine.worktrees import (
        _create_or_attach_worktree,
        _decide_worktree_prep,
        _ensure_todo_on_remote_main,
        _prepare_worktree,
        _write_worktree_prep_state,
    )

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
    modified_files, untracked_files, deleted_files = _classify_porcelain_status(status_output)

    # Scope to caller's files when --paths is provided
    if paths:
        modified_files = _filter_by_paths(modified_files, paths)
        untracked_files = _filter_by_paths(untracked_files, paths)
        deleted_files = _filter_by_paths(deleted_files, paths)

    all_changed = modified_files + untracked_files + deleted_files
    if not all_changed:
        raise ValueError("No matching uncommitted changes for the given paths.")

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
    _write_file(todo_dir / "demo.md", f"<!-- no-demo: from-main inline work -->\n# Demo: {slug}\n")

    # --- 5d. Push todo scaffold to remote ---
    pushed, push_reason = _ensure_todo_on_remote_main(cwd, slug)
    if not pushed and push_reason not in ("already_on_remote",):
        raise RuntimeError(f"Failed to push todo scaffold to remote: {push_reason}")

    # --- 5e. Create worktree ---
    created = _create_or_attach_worktree(cwd, slug)
    worktree_path = project_root / WORKTREE_DIR / slug

    # Run prep if needed
    prep_decision = _decide_worktree_prep(cwd, slug, created=created)
    if prep_decision.should_prepare:
        _prepare_worktree(cwd, slug)
        _write_worktree_prep_state(cwd, slug, prep_decision.inputs_digest)

    # --- 5f. Transfer changes to worktree ---
    _transfer_files_to_worktree(project_root, worktree_path, modified_files, untracked_files, deleted_files)

    # --- 5g. Clean main working tree ---
    _clean_main_working_tree(repo, project_root, modified_files, untracked_files)

    # --- 5h. Set state for review dispatch ---
    worktree_cwd = str(worktree_path)
    mark_ready(worktree_cwd, slug)
    mark_phase(worktree_cwd, slug, "build", "complete")

    # --- 5i. Return instructions ---
    return (
        f"Todo created: {slug}\n"
        f"Worktree: {WORKTREE_DIR}/{slug}/\n"
        "\n"
        "Next steps:\n"
        f"  1. cd {WORKTREE_DIR}/{slug}\n"
        '  2. git add -A && git commit -m "your commit message"\n'
        f"  3. telec sessions run --command /next-work --args {slug} --project {cwd} --detach"
    )