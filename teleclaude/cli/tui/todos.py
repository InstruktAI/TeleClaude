"""Todo item model for TUI views."""

from __future__ import annotations

from dataclasses import dataclass, field

from teleclaude.cli.tui.types import TodoStatus


@dataclass
class TodoItem:
    """Todo item consumed by the PreparationView."""

    slug: str
    status: TodoStatus
    description: str | None
    has_requirements: bool
    has_impl_plan: bool
    build_status: str | None = None
    review_status: str | None = None
    deferrals_status: str | None = None
    files: list[str] = field(default_factory=list)
    version_total: int = 0
    after: list[str] = field(default_factory=list)
    group: str | None = None
    kind: str | None = None
    lifecycle_phase: str | None = None
    integration_phase: str | None = None
    finalize_status: str | None = None
    hold: bool = False
    held: bool = False
    hold_source: str | None = None
    active_runner: str | None = None
    schedule: str | None = None
    task_plan_digest: str | None = None
    task_approved_digest: str | None = None
    project_path: str | None = None
    is_holder: bool = False
    todo_id: str | None = None
    removed_at: str | None = None
    delivered_at: str | None = None
    created_by_principal: str | None = None
