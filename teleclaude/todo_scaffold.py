"""Scaffold todo folders with canonical TeleClaude artifacts."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from teleclaude.constants import WORKTREE_DIR
from teleclaude.slug import ensure_unique_slug, validate_slug
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
    slug = ensure_unique_slug(todos_root, slug)
    todo_dir = todos_root / slug

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
    slug = ensure_unique_slug(todos_root, slug)
    todo_dir = todos_root / slug

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


def _emit_prepare_event(event_type: str, payload: dict[str, object]) -> None:
    """Fire-and-forget prepare lifecycle event (mirrors core helper)."""
    from teleclaude.core.next_machine.core import _emit_prepare_event as _core_emit

    _core_emit(event_type, payload)


def _inherit_parent_phase(
    *,
    project_root: Path,
    parent_slug: str,
    child_slug: str,
    child_dir: Path,
    parent_req_review: dict[str, object],
    parent_plan_review: dict[str, object],
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
        child_state["requirements_review"] = dict(parent_req_review)  # type: ignore[assignment]
    if plan_approved:
        child_state["plan_review"] = dict(parent_plan_review)  # type: ignore[assignment]

    # Set phase
    child_state["prepare_phase"] = inherited_phase

    # Record skipped audit entries
    audit = child_state.get("audit")
    if not isinstance(audit, dict):
        audit = {}
        child_state["audit"] = audit  # type: ignore[assignment]
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
    state["breakdown"] = {"assessed": True, "todos": child_slugs}
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
