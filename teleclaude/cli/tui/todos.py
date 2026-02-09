"""Todo item model for TUI views."""

from dataclasses import dataclass

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
