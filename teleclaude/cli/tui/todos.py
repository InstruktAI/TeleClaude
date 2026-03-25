"""Todo item model for TUI views."""

from dataclasses import dataclass, field

from teleclaude.cli.tui.types import TodoStatus


@dataclass
class TodoItem:  # pylint: disable=too-many-instance-attributes
    """Todo item consumed by the PreparationView."""

    slug: str
    status: TodoStatus
    description: str | None
    has_requirements: bool
    has_impl_plan: bool
    build_status: str | None = None
    review_status: str | None = None
    dor_score: int | None = None
    deferrals_status: str | None = None
    findings_count: int = 0
    files: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    group: str | None = None
    prepare_phase: str | None = None
    integration_phase: str | None = None
    finalize_status: str | None = None
    todo_path: str | None = None  # Always set by assemble_roadmap; None = contract violation

    def file_path(self, filename: str) -> str:
        """Resolve the absolute path for a file within this todo."""
        if self.todo_path is None:
            raise ValueError(f"todo_path not set for '{self.slug}'")
        return f"{self.todo_path}/{filename}"
