"""Parse todos from roadmap.md."""

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel


@dataclass
class TodoItem:
    """Parsed todo item from roadmap.md."""

    slug: str
    status: str  # "pending", "ready", "in_progress"
    description: str | None
    has_requirements: bool
    has_impl_plan: bool
    build_status: str | None = None  # From state.json: "pending", "complete"
    review_status: str | None = None  # From state.json: "pending", "approved", "changes_requested"


# Status marker mapping
STATUS_MAP: dict[str, str] = {
    " ": "pending",
    ".": "ready",
    ">": "in_progress",
}


def parse_roadmap(project_path: str) -> list[TodoItem]:
    r"""Parse todos from todos/roadmap.md.

    Pattern: ^-\s+\[([ .>])\]\s+(\S+)
    Description is the indented text following the slug line.

    Args:
        project_path: Absolute path to project directory

    Returns:
        List of parsed todo items
    """
    roadmap_path = Path(project_path) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return []

    content = roadmap_path.read_text()
    todos: list[TodoItem] = []

    # Pattern for todo line: - [ ] slug-name or - [.] slug-name or - [>] slug-name
    pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)

    lines = content.split("\n")
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            status_char = match.group(1)
            slug = match.group(2)

            # Extract description (next indented lines)
            description = ""
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if next_line.startswith("      "):  # 6 spaces = indented
                    description += next_line.strip() + " "
                elif next_line.strip() == "":
                    continue
                else:
                    break

            # Check for requirements.md and implementation-plan.md
            todos_dir = Path(project_path) / "todos" / slug
            has_requirements = (todos_dir / "requirements.md").exists()
            has_impl_plan = (todos_dir / "implementation-plan.md").exists()

            # Read state.json from worktree (trees/{slug}/todos/{slug}/state.json)
            # or main repo (todos/{slug}/state.json)
            build_status, review_status = _read_state(project_path, slug)

            todos.append(
                TodoItem(
                    slug=slug,
                    status=STATUS_MAP.get(status_char, "pending"),
                    description=description.strip() or None,
                    has_requirements=has_requirements,
                    has_impl_plan=has_impl_plan,
                    build_status=build_status,
                    review_status=review_status,
                )
            )

    return todos


def _read_state(project_path: str, slug: str) -> tuple[str | None, str | None]:
    """Read build/review status from state.json.

    Checks both worktree and main repo locations.

    Args:
        project_path: Absolute path to project directory
        slug: Todo slug

    Returns:
        Tuple of (build_status, review_status)
    """
    # Try worktree first (trees/{slug}/todos/{slug}/state.json)
    worktree_state = Path(project_path) / "trees" / slug / "todos" / slug / "state.json"
    if worktree_state.exists():
        return _parse_state_file(worktree_state)

    # Fall back to main repo (todos/{slug}/state.json)
    main_state = Path(project_path) / "todos" / slug / "state.json"
    if main_state.exists():
        return _parse_state_file(main_state)

    return None, None


def _parse_state_file(state_path: Path) -> tuple[str | None, str | None]:
    """Parse a state.json file.

    Args:
        state_path: Path to state.json

    Returns:
        Tuple of (build_status, review_status)
    """
    try:
        content = state_path.read_text()
    except OSError:
        return None, None

    try:
        state = _StateData.model_validate_json(content)
    except ValueError:
        return None, None

    return state.build, state.review


class _StateData(BaseModel):
    """Typed state.json payload."""

    build: str | None = None
    review: str | None = None
