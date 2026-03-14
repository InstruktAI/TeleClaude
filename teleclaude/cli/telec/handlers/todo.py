"""Handlers for telec todo commands."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.todo_scaffold import create_todo_skeleton

__all__ = [
    "_handle_todo",
    "_handle_todo_create",
    "_handle_todo_dump",
    "_handle_todo_mark_ready",
    "_handle_todo_remove",
    "_handle_todo_split",
    "_handle_todo_validate",
    "_handle_todo_verify_artifacts",
]


def _handle_todo_mark_ready(args: list[str]) -> None:
    """Handle telec todo mark-ready <slug> [<slug> ...].

    Fast-track one or more TODOs to work-ready state, bypassing the full prepare lifecycle.
    Promotes input.md → requirements.md, generates implementation-plan.md and quality-checklist.md,
    and sets state.yaml to satisfy all work state machine entry conditions.
    """
    from teleclaude.core.next_machine.state_io import mark_ready

    if not args:
        print("Usage: telec todo mark-ready <slug> [<slug> ...]")
        raise SystemExit(1)

    slugs = [a for a in args if not a.startswith("-")]
    if not slugs:
        print("Missing required argument: <slug>")
        raise SystemExit(1)

    cwd = str(Path.cwd())
    failed = 0
    for slug in slugs:
        ok, msg = mark_ready(cwd, slug)
        print(msg)
        if not ok:
            failed += 1

    if failed:
        raise SystemExit(1)


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    from teleclaude.cli.telec.handlers.demo import _handle_todo_demo
    from teleclaude.cli.tool_commands import (
        handle_todo_create,
        handle_todo_integrate,
        handle_todo_mark_finalize_ready,
        handle_todo_mark_phase,
        handle_todo_prepare,
        handle_todo_set_deps,
        handle_todo_work,
    )

    if not args:
        print(_usage("todo"))
        return

    subcommand = args[0]
    if subcommand == "create":
        handle_todo_create(args[1:])
    elif subcommand == "scaffold":
        _handle_todo_create(args[1:])
    elif subcommand == "remove":
        _handle_todo_remove(args[1:])
    elif subcommand == "validate":
        _handle_todo_validate(args[1:])
    elif subcommand == "demo":
        _handle_todo_demo(args[1:])
    elif subcommand == "prepare":
        handle_todo_prepare(args[1:])
    elif subcommand == "work":
        handle_todo_work(args[1:])
    elif subcommand == "integrate":
        handle_todo_integrate(args[1:])
    elif subcommand == "mark-phase":
        handle_todo_mark_phase(args[1:])
    elif subcommand == "mark-finalize-ready":
        handle_todo_mark_finalize_ready(args[1:])
    elif subcommand == "set-deps":
        handle_todo_set_deps(args[1:])
    elif subcommand == "verify-artifacts":
        _handle_todo_verify_artifacts(args[1:])
    elif subcommand == "dump":
        _handle_todo_dump(args[1:])
    elif subcommand == "split":
        _handle_todo_split(args[1:])
    elif subcommand == "mark-ready":
        _handle_todo_mark_ready(args[1:])
    else:
        print(f"Unknown todo subcommand: {subcommand}")
        print(_usage("todo"))
        raise SystemExit(1)


def _handle_todo_validate(args: list[str]) -> None:
    """Handle telec todo validate."""

    from teleclaude.resource_validation import validate_all_todos, validate_todo

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "validate"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed for validation.")
                print(_usage("todo", "validate"))
                raise SystemExit(1)
            slug = arg
            i += 1

    errors = []
    if slug:
        errors = validate_todo(slug, project_root)
    else:
        errors = validate_all_todos(project_root)

    if errors:
        print("Todo validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if slug:
        print(f"✓ Todo {slug} is valid")
    else:
        print("✓ All active todos are valid")


def _handle_todo_verify_artifacts(args: list[str]) -> None:
    """Handle telec todo verify-artifacts <slug> --phase <build|review>."""
    from teleclaude.core.next_machine.core import is_bug_todo, verify_artifacts

    slug: str | None = None
    phase: str | None = None
    cwd = str(Path.cwd())

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--phase",) and i + 1 < len(args):
            phase = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "verify-artifacts"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "verify-artifacts"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if slug is None:
        print("Missing required argument: <slug>")
        print(_usage("todo", "verify-artifacts"))
        raise SystemExit(1)
    if phase is None:
        print("Missing required flag: --phase <build|review>")
        print(_usage("todo", "verify-artifacts"))
        raise SystemExit(1)
    if phase not in ("build", "review"):
        print(f"Invalid phase: {phase!r} (expected 'build' or 'review')")
        raise SystemExit(1)

    is_bug = is_bug_todo(cwd, slug)
    passed, report = verify_artifacts(cwd, slug, phase, is_bug=is_bug)
    print(report)
    raise SystemExit(0 if passed else 1)


def _handle_todo_dump(args: list[str]) -> None:
    """Handle telec todo dump <slug> <content> [--after <deps>]."""
    if len(args) < 2:
        print(_usage("todo", "dump"))
        return

    slug: str | None = None
    content: str | None = None
    project_root = Path.cwd()
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "dump"))
            raise SystemExit(1)
        else:
            if slug is None:
                slug = arg
            elif content is None:
                content = arg
            else:
                print("Too many positional arguments.")
                print(_usage("todo", "dump"))
                raise SystemExit(1)
            i += 1

    if not slug or not content:
        print(_usage("todo", "dump"))
        raise SystemExit(1)

    # Always register in roadmap (unlike create, which only registers with --after)
    after_deps = after if after is not None else []

    try:
        todo_dir = create_todo_skeleton(project_root, slug, after=after_deps)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    slug = todo_dir.name  # Use resolved name in case collision resolution renamed it

    # Overwrite input.md with brain dump content
    input_path = todo_dir / "input.md"
    input_path.write_text(f"# {todo_dir.name} — Input\n\n{content}\n", encoding="utf-8")

    # Emit todo.dumped notification via daemon API
    _log = get_logger(__name__)
    try:
        envelope = EventEnvelope(
            event="todo.dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="todo",
            description=f"Todo dumped: {slug}",
            payload={"slug": slug, "project_root": str(project_root)},
        )
        tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
        _log.info("Dumped todo: todos/%s/ — notification sent.", slug)
    except Exception:
        _log.warning("Dumped todo: todos/%s/ — notification emission failed", slug)


def _handle_todo_split(args: list[str]) -> None:
    """Handle telec todo split <slug> --into <child1> [<child2> ...]."""
    from teleclaude.todo_scaffold import split_todo

    if not args:
        print(_usage("todo", "split"))
        return

    slug: str | None = None
    children: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--into" and i + 1 < len(args):
            i += 1
            children.append(args[i])
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "split"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one parent slug is allowed.")
                print(_usage("todo", "split"))
                raise SystemExit(1)
            slug = arg
        i += 1

    if not slug:
        print("Missing required argument: <slug>")
        print(_usage("todo", "split"))
        raise SystemExit(1)

    if not children:
        print("Missing required flag: --into <child> (at least one)")
        print(_usage("todo", "split"))
        raise SystemExit(1)

    project_root = Path.cwd()
    try:
        created = split_todo(project_root, slug, children)
        print(f"Split '{slug}' into {len(created)} children: {', '.join(children)}")
        for d in created:
            print(f"  Created: {d}")
    except (FileNotFoundError, ValueError, FileExistsError) as e:
        print(f"Error: {e}")
        raise SystemExit(1) from e


def _handle_todo_create(args: list[str]) -> None:
    """Handle telec todo create."""
    if not args:
        print(_usage("todo", "create"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "create"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "create"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "create"))
        raise SystemExit(1)

    try:
        todo_dir = create_todo_skeleton(project_root, slug, after=after)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Created todo skeleton: {todo_dir}")
    if after:
        print(f"Updated dependencies for {todo_dir.name}: {', '.join(after)}")


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove."""
    from teleclaude.todo_scaffold import remove_todo

    if not args:
        print(_usage("todo", "remove"))
        return

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "remove"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "remove"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "remove"))
        raise SystemExit(1)

    try:
        remove_todo(project_root, slug)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Removed todo: {slug}")
