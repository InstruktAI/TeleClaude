"""Handlers for telec bugs commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.models import CreateSessionResult
from teleclaude.cli.telec.help import _usage
from teleclaude.constants import WORKTREE_DIR
from teleclaude.slug import normalize_slug
from teleclaude.todo_scaffold import create_bug_skeleton

__all__ = [
    "_handle_bugs",
    "_handle_bugs_create",
    "_handle_bugs_list",
    "_handle_bugs_report",
]


def _handle_bugs(args: list[str]) -> None:
    """Handle telec bugs commands."""
    if not args:
        print(_usage("bugs"))
        return

    subcommand = args[0]
    if subcommand == "report":
        _handle_bugs_report(args[1:])
    elif subcommand == "create":
        _handle_bugs_create(args[1:])
    elif subcommand == "list":
        _handle_bugs_list(args[1:])
    else:
        print(f"Unknown bugs subcommand: {subcommand}")
        print(_usage("bugs"))
        raise SystemExit(1)


def _handle_bugs_create(args: list[str]) -> None:
    """Handle telec bugs create <slug>."""
    if not args:
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec bugs create <slug>")
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print("Usage: telec bugs create <slug>")
                raise SystemExit(1)
            slug = arg
            i += 1

    if slug is None:
        print("Error: slug is required")
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    try:
        bug_dir = create_bug_skeleton(
            project_root=project_root,
            slug=slug,
            description="",
        )
        print(f"Created bug skeleton: {bug_dir}")
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)


def _handle_bugs_report(args: list[str]) -> None:
    """Handle telec bugs report <description> [--slug <slug>]."""
    if not args:
        print(_usage("bugs", "report"))
        return

    description: str | None = None
    slug: str | None = None
    body: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg == "--body" and i + 1 < len(args):
            body = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "report"))
            raise SystemExit(1)
        else:
            if description is not None:
                print("Only one description is allowed.")
                print(_usage("bugs", "report"))
                raise SystemExit(1)
            description = arg
            i += 1

    if not description:
        print("Missing required description.")
        print(_usage("bugs", "report"))
        raise SystemExit(1)

    # Auto-generate slug if not provided
    if not slug:
        slug_base = normalize_slug(description)
        if len(slug_base) > 40:
            slug_base = slug_base[:40].rstrip("-")
        slug = f"fix-{slug_base}"

    try:
        todo_dir = create_bug_skeleton(
            project_root,
            slug,
            description,
            body=body or "",
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    slug = todo_dir.name

    # Dispatch orchestrator on mainline — the state machine handles branches/worktrees
    async def _dispatch_bug_fix() -> CreateSessionResult:
        api = TelecAPIClient()
        await api.connect()
        try:
            return await api.create_session(
                computer="local",
                project_path=str(project_root),
                agent="claude",
                thinking_mode="slow",
                title=f"Bug fix: {slug}",
                message=f"Run telec todo work {slug} and follow output verbatim until done.",
                skip_listener_registration=True,
            )
        finally:
            await api.close()

    try:
        result = asyncio.run(_dispatch_bug_fix())
        print(f"Created bug todo: {todo_dir}")
        print(f"Bug slug: {slug}")
        print(f"Orchestrator session: {result.session_id}")
    except Exception as exc:
        print(f"Error dispatching orchestrator: {exc}")
        print(f"Bug scaffold created at {todo_dir}.")
        print(f"Start orchestrator manually: telec todo work {slug}")


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list."""
    import yaml

    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)
        else:
            print(f"Unexpected argument: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)

    todos_dir = project_root / "todos"
    if not todos_dir.exists():
        print("No bugs found")
        return

    bugs = []
    for todo_dir in sorted(todos_dir.iterdir()):
        if not todo_dir.is_dir() or todo_dir.name.startswith("."):
            continue

        bug_md = todo_dir / "bug.md"
        state_yaml = todo_dir / "state.yaml"
        worktree_state = project_root / WORKTREE_DIR / todo_dir.name / "todos" / todo_dir.name / "state.yaml"
        state_path = worktree_state if worktree_state.exists() else state_yaml

        if not bug_md.exists():
            continue

        # Read state to determine status
        status = "unknown"
        if state_path.exists():
            try:
                state = yaml.safe_load(state_path.read_text())
                build = state.get("build", "pending")
                review = state.get("review", "pending")

                if review == "approved":
                    status = "approved"
                elif review == "changes_requested":
                    status = "fixing"
                elif build == "complete":
                    status = "reviewing"
                elif build in ("started", "complete"):
                    status = "building"
                else:
                    status = "pending"
            except (yaml.YAMLError, OSError):
                pass

        bugs.append((todo_dir.name, status))

    if not bugs:
        print("No bugs found")
        return

    print(f"Bug fixes ({len(bugs)}):\n")
    print(f"{'Slug':<40} {'Status':<15}")
    print("-" * 60)
    for slug, status in bugs:
        print(f"{slug:<40} {status:<15}")
