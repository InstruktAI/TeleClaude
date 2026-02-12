"""Todo item model for TUI views."""

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
    dor_status: str | None = None
    dor_score: int | None = None
    deferrals_status: str | None = None
    findings_count: int = 0
    files: list[str] = field(default_factory=list)
