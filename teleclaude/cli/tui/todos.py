"""Parse todos from roadmap.md."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TodoItem:
    """Parsed todo item from roadmap.md."""

    slug: str
    status: str  # "pending", "ready", "in_progress"
    description: str | None
    has_requirements: bool
    has_impl_plan: bool


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

            todos.append(
                TodoItem(
                    slug=slug,
                    status=STATUS_MAP.get(status_char, "pending"),
                    description=description.strip() or None,
                    has_requirements=has_requirements,
                    has_impl_plan=has_impl_plan,
                )
            )

    return todos
