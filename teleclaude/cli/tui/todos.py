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
    lifecycle_phase: str | None = None
    integration_phase: str | None = None
    finalize_status: str | None = None
    project_path: str | None = None
    is_holder: bool = False
