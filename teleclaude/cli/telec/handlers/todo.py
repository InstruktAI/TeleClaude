"""Handlers for telec todo commands."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.handlers._arg_parsing import parse_slug_after_args
from teleclaude.cli.telec.handlers.demo import _handle_todo_demo
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import ToolAPIError, tool_api_request
from teleclaude.cli.tool_commands import (
    handle_todo_create as _handle_machine_todo_create,
)
from teleclaude.cli.tool_commands import (
    handle_todo_integrate,
    handle_todo_mark_finalize_ready,
    handle_todo_mark_phase,
    handle_todo_prepare,
    handle_todo_set_deps,
    handle_todo_work,
)
from teleclaude.core.next_machine.state_io import mark_ready
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.todo_scaffold import (
    create_todo_skeleton,
)

__all__ = [
    "_handle_todo",
    "_handle_todo_create",
    "_handle_todo_dump",
    "_handle_todo_from_main",
    "_handle_todo_mark_ready",
    "_handle_todo_remove",
    "_handle_todo_split",
    "_handle_todo_validate",
    "_handle_todo_verify_artifacts",
]

_IGNORED_REMOTE_PUSH_REASONS = {"already_on_remote", "no_local_artifacts", "not_a_repo"}


def _load_resource_validation_module():
    """Load validation helpers lazily so tests can patch the module."""
    return importlib.import_module("teleclaude.resource_validation")


def _load_build_gates_module():
    """Load build gate helpers lazily so tests can patch the module."""
    return importlib.import_module("teleclaude.core.next_machine.core")


def _load_worktrees_module():
    """Load worktree helpers lazily so tests can patch the module."""
    return importlib.import_module("teleclaude.core.next_machine.worktrees")


def _load_todo_scaffold_module():
    """Load scaffold helpers lazily so tests can patch the module."""
    return importlib.import_module("teleclaude.todo_scaffold")


def _handle_todo_mark_ready(args: list[str]) -> None:
    """Handle telec todo mark-ready <slug> [<slug> ...].

    Fast-track one or more TODOs to work-ready state, bypassing the full prepare lifecycle.
    Promotes input.md → requirements.md, generates implementation-plan.md and quality-checklist.md,
    and sets state.yaml to satisfy all work state machine entry conditions.
    """
    if not args:
        print("Usage: telec todo mark-ready <slug> [<slug> ...]")
        raise SystemExit(1)

    slugs = [arg for arg in args if not arg.startswith("-")]
    if not slugs:
        print("Missing required argument: <slug>")
        raise SystemExit(1)

    cwd = str(Path.cwd())
    failed = 0
    for slug in slugs:
        ok, message = mark_ready(cwd, slug)
        print(message)
        if not ok:
            failed += 1

    if failed:
        raise SystemExit(1)


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    if not args:
        print(_usage("todo"))
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "create": _handle_machine_todo_create,
        "scaffold": _handle_todo_create,
        "remove": _handle_todo_remove,
        "validate": _handle_todo_validate,
        "demo": _handle_todo_demo,
        "prepare": handle_todo_prepare,
        "work": handle_todo_work,
        "integrate": handle_todo_integrate,
        "mark-phase": handle_todo_mark_phase,
        "mark-finalize-ready": handle_todo_mark_finalize_ready,
        "set-deps": handle_todo_set_deps,
        "verify-artifacts": _handle_todo_verify_artifacts,
        "dump": _handle_todo_dump,
        "split": _handle_todo_split,
        "mark-ready": _handle_todo_mark_ready,
        "from-main": _handle_todo_from_main,
    }

    subcommand = args[0]
    handler = handlers.get(subcommand)
    if handler is None:
        print(f"Unknown todo subcommand: {subcommand}")
        print(_usage("todo"))
        raise SystemExit(1)
    handler(args[1:])


def _handle_todo_validate(args: list[str]) -> None:
    """Handle telec todo validate."""
    slug: str | None = None
    project_root = Path.cwd()

    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "validate"))
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed for validation.")
            print(_usage("todo", "validate"))
            raise SystemExit(1)
        slug = arg
        index += 1

    validation = _load_resource_validation_module()
    errors = validation.validate_todo(slug, project_root) if slug else validation.validate_all_todos(project_root)
    if errors:
        print("Todo validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if slug:
        print(f"✓ Todo {slug} is valid")
        return
    print("✓ All active todos are valid")


def _handle_todo_verify_artifacts(args: list[str]) -> None:
    """Handle telec todo verify-artifacts <slug> --phase <build|review>."""
    slug: str | None = None
    phase: str | None = None
    cwd = str(Path.cwd())

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--phase" and index + 1 < len(args):
            phase = args[index + 1]
            index += 2
            continue
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "verify-artifacts"))
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed.")
            print(_usage("todo", "verify-artifacts"))
            raise SystemExit(1)
        slug = arg
        index += 1

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

    build_gates = _load_build_gates_module()
    passed, report = build_gates.verify_artifacts(cwd, slug, phase, is_bug=build_gates.is_bug_todo(cwd, slug))
    print(report)
    raise SystemExit(0 if passed else 1)


def _parse_todo_dump_args(args: list[str]) -> tuple[str, str, list[str]]:
    if len(args) < 2:
        print(_usage("todo", "dump"))
        raise SystemExit(1)

    slug: str | None = None
    content: str | None = None
    after: list[str] = []
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--after" and index + 1 < len(args):
            after = [part.strip() for part in args[index + 1].split(",") if part.strip()]
            index += 2
            continue
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "dump"))
            raise SystemExit(1)
        if slug is None:
            slug = arg
        elif content is None:
            content = arg
        else:
            print("Too many positional arguments.")
            print(_usage("todo", "dump"))
            raise SystemExit(1)
        index += 1

    if not slug or not content:
        print(_usage("todo", "dump"))
        raise SystemExit(1)
    return slug, content, after


def _emit_todo_dump_event(project_root: Path, slug: str, logger_name: str) -> None:
    logger = get_logger(logger_name)
    try:
        envelope = EventEnvelope(
            event="domain.software-development.planning.todo_dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=f"Todo dumped: {slug}",
            payload={"slug": slug, "project_root": str(project_root)},
        )
        tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
        logger.info("Dumped todo: todos/%s/ — notification sent.", slug)
    except (OSError, RuntimeError, ToolAPIError, ValueError):
        logger.warning("Dumped todo: todos/%s/ — notification emission failed", slug)


def _ensure_todo_remote_sync(project_root: Path, slug: str) -> tuple[bool, str]:
    ensure_todo = _load_worktrees_module()._ensure_todo_on_remote_main  # pylint: disable=protected-access
    return ensure_todo(str(project_root), slug)


def _report_remote_push(project_root: Path, slug: str, success_message: str, warning_message: str) -> None:
    pushed, reason = _ensure_todo_remote_sync(project_root, slug)
    if pushed:
        print(success_message.format(slug=slug, reason=reason))
        return
    if reason not in _IGNORED_REMOTE_PUSH_REASONS:
        print(warning_message.format(slug=slug, reason=reason))


def _handle_todo_dump(args: list[str]) -> None:
    """Handle telec todo dump <slug> <content> [--after <deps>]."""
    slug, content, after = _parse_todo_dump_args(args)
    project_root = Path.cwd()

    try:
        todo_dir = create_todo_skeleton(project_root, slug, after=after)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    resolved_slug = todo_dir.name
    input_path = todo_dir / "input.md"
    input_path.write_text(f"# {resolved_slug} — Input\n\n{content}\n", encoding="utf-8")
    _emit_todo_dump_event(project_root, resolved_slug, __name__)
    _report_remote_push(
        project_root,
        resolved_slug,
        "Scaffold for {slug} pushed to remote: {reason}",
        "Warning: Scaffold for {slug} not pushed to remote: {reason}",
    )


def _parse_todo_split_args(args: list[str]) -> tuple[str, list[str]]:
    if not args:
        print(_usage("todo", "split"))
        raise SystemExit(1)

    slug: str | None = None
    children: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--into" and index + 1 < len(args):
            index += 1
            children.append(args[index])
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "split"))
            raise SystemExit(1)
        elif slug is not None:
            print("Only one parent slug is allowed.")
            print(_usage("todo", "split"))
            raise SystemExit(1)
        else:
            slug = arg
        index += 1

    if not slug:
        print("Missing required argument: <slug>")
        print(_usage("todo", "split"))
        raise SystemExit(1)
    if not children:
        print("Missing required flag: --into <child> (at least one)")
        print(_usage("todo", "split"))
        raise SystemExit(1)
    return slug, children


def _report_split_remote_pushes(project_root: Path, slug: str, children: list[str]) -> None:
    _report_remote_push(
        project_root,
        slug,
        "Parent '{slug}' update pushed to remote: {reason}",
        "Warning: Parent '{slug}' scaffold not pushed to remote: {reason}",
    )
    for child in children:
        _report_remote_push(
            project_root,
            child,
            "Child '{slug}' pushed to remote: {reason}",
            "Warning: Child '{slug}' scaffold not pushed to remote: {reason}",
        )


def _handle_todo_split(args: list[str]) -> None:
    """Handle telec todo split <slug> --into <child1> [<child2> ...]."""
    slug, children = _parse_todo_split_args(args)
    project_root = Path.cwd()
    try:
        created = _load_todo_scaffold_module().split_todo(project_root, slug, children)
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Split '{slug}' into {len(created)} children: {', '.join(children)}")
    for directory in created:
        print(f"  Created: {directory}")
    _report_split_remote_pushes(project_root, slug, children)


def _parse_todo_create_args(args: list[str]) -> tuple[str, list[str] | None]:
    if not args:
        print(_usage("todo", "create"))
        raise SystemExit(1)
    return parse_slug_after_args(args, lambda: _usage("todo", "create"))


def _handle_todo_create(args: list[str]) -> None:
    """Handle telec todo create."""
    slug, after = _parse_todo_create_args(args)
    project_root = Path.cwd()

    try:
        todo_dir = create_todo_skeleton(project_root, slug, after=after)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Created todo skeleton: {todo_dir}")
    if after:
        print(f"Updated dependencies for {todo_dir.name}: {', '.join(after)}")
    _report_remote_push(
        project_root,
        slug,
        "Scaffold for {slug} pushed to remote: {reason}",
        "Warning: Scaffold for {slug} not pushed to remote: {reason}",
    )


def _parse_single_slug_arg(args: list[str], subcommand: str, missing_message: str, duplicate_message: str) -> str:
    if not args:
        print(_usage("todo", subcommand))
        raise SystemExit(1)

    slug: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", subcommand))
            raise SystemExit(1)
        if slug is not None:
            print(duplicate_message)
            print(_usage("todo", subcommand))
            raise SystemExit(1)
        slug = arg
        index += 1

    if not slug:
        print(missing_message)
        print(_usage("todo", subcommand))
        raise SystemExit(1)
    return slug


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove."""
    slug = _parse_single_slug_arg(args, "remove", "Missing required slug.", "Only one slug is allowed.")
    project_root = Path.cwd()

    try:
        _load_todo_scaffold_module().remove_todo(project_root, slug)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Removed todo: {slug}")


def _parse_from_main_args(args: list[str]) -> tuple[str, str | None]:
    slug: str | None = None
    description: str | None = None
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--slug" and index + 1 < len(args):
            slug = args[index + 1]
            index += 2
            continue
        if arg == "--description" and index + 1 < len(args):
            description = args[index + 1]
            index += 2
            continue
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "from-main"))
            raise SystemExit(1)
        print(f"Unexpected argument: {arg}")
        print(_usage("todo", "from-main"))
        raise SystemExit(1)

    if not slug:
        print("Missing required flag: --slug <name>")
        print(_usage("todo", "from-main"))
        raise SystemExit(1)
    return slug, description


def _handle_todo_from_main(args: list[str]) -> None:
    """Handle telec todo from-main --slug <name> [--description <desc>]."""
    slug, description = _parse_from_main_args(args)
    project_root = str(Path.cwd())
    try:
        output = _load_todo_scaffold_module().create_from_main_skeleton(project_root, slug, description=description)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(output)
