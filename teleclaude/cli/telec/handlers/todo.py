"""Handlers for telec todo commands."""
# pylint: disable=import-outside-toplevel,too-many-branches,too-many-locals,too-many-statements
# pylint: disable=no-else-raise,broad-exception-caught

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.events.envelope import EventEnvelope, EventLevel

__all__ = [
    "_handle_todo",
    "_handle_todo_artifacts",
    "_handle_todo_dump",
    "_handle_todo_from_main",
    "_handle_todo_mark_ready",
    "_handle_todo_remove",
    "_handle_todo_show",
    "_handle_todo_split",
    "_handle_todo_stamp",
    "_handle_todo_validate",
    "_handle_todo_verify_artifacts",
]


def _handle_todo_mark_ready(args: list[str]) -> None:
    """Handle telec todo mark-ready <slug> [<slug> ...].

    Fast-track one or more TODOs to work-ready state, bypassing the full prepare lifecycle.
    Validates required artifacts exist, then targets the 'prepared' state which stamps
    DOR, grounding, and review verdicts.
    """
    from teleclaude.core.next_machine.state_io import mark_phase

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
        try:
            mark_phase(cwd, slug, "prepared")
            print(f"✓ {slug} fast-tracked to work-ready (prepared)")
        except (ValueError, FileNotFoundError) as exc:
            print(str(exc))
            failed += 1

    if failed:
        raise SystemExit(1)


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    from teleclaude.cli.tool_commands import (
        handle_todo_create,
        handle_todo_integrate,
        handle_todo_mark_phase,
        handle_todo_prepare,
        handle_todo_set_deps,
        handle_todo_work,
    )

    if not args:
        print(_usage("todo"))
        return

    subcommand = args[0]
    if subcommand == "co-create":
        handle_todo_create(args[1:])
    elif subcommand == "remove":
        _handle_todo_remove(args[1:])
    elif subcommand == "validate":
        _handle_todo_validate(args[1:])
    elif subcommand == "prepare":
        handle_todo_prepare(args[1:])
    elif subcommand == "work":
        handle_todo_work(args[1:])
    elif subcommand == "integrate":
        handle_todo_integrate(args[1:])
    elif subcommand == "mark-phase":
        handle_todo_mark_phase(args[1:])
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
    elif subcommand == "from-main":
        _handle_todo_from_main(args[1:])
    elif subcommand == "artifacts":
        _handle_todo_artifacts(args[1:])
    elif subcommand == "stamp":
        _handle_todo_stamp(args[1:])
    elif subcommand == "show":
        _handle_todo_show(args[1:])
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
    """Handle telec todo dump <slug> <content> [--after <deps>].

    Creates a todo in todos.db: state, input artifact, and roadmap entry.
    No filesystem writes. No git commits.
    """
    if len(args) < 2:
        print(_usage("todo", "dump"))
        raise SystemExit(1)

    slug: str | None = None
    content: str | None = None
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

    # Create via daemon API — writes state + input artifact + roadmap entry to todos.db
    result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body={
            "slug": slug,
            "content": content,
            "after": after or [],
            "cwd": str(Path.cwd()),
        },
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Dumped todo: {slug}")
    else:
        print(f"Error: unexpected response: {result}")
        raise SystemExit(1)

    # Emit planning.todo_dumped notification
    _log = get_logger(__name__)
    try:
        envelope = EventEnvelope(
            event="domain.software-development.planning.todo_dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=f"Todo dumped: {slug}",
            payload={"slug": slug, "project_root": str(Path.cwd())},
        )
        tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
    except Exception:
        _log.warning("Todo dumped but notification emission failed: %s", slug)


def _handle_todo_split(args: list[str]) -> None:
    """Handle telec todo split <slug> --into <child1> [<child2> ...].

    Creates children in todos.db, updates parent breakdown state.
    No filesystem writes. No git commits.
    """
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

    result = tool_api_request(
        "POST",
        "/todos/split",
        json_body={"slug": slug, "children": children, "cwd": str(Path.cwd())},
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Split '{slug}' into {len(children)} children: {', '.join(children)}")
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(f"Error: {result}")
        raise SystemExit(1)


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove — delete state, artifacts, and roadmap entry from todos.db.

    Also cleans up worktree and branch if they exist.
    """
    if not args:
        print(_usage("todo", "remove"))
        raise SystemExit(1)

    slug: str | None = None

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

    result = tool_api_request(
        "POST",
        "/todos/remove",
        json_body={"slug": slug, "cwd": str(Path.cwd())},
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Removed todo: {slug}")
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(f"Error: {result}")
        raise SystemExit(1)


def _handle_todo_from_main(args: list[str]) -> None:
    """Handle telec todo from-main --slug <name> [--description <desc>] [--all]."""
    from teleclaude.todo_scaffold import create_from_main_skeleton

    slug: str | None = None
    description: str | None = None
    all_files = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg == "--description" and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif arg == "--all":
            all_files = True
            i += 1
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "from-main"))
            raise SystemExit(1)
        else:
            print(f"Unexpected argument: {arg}")
            print(_usage("todo", "from-main"))
            raise SystemExit(1)

    if not slug:
        print("Missing required flag: --slug <name>")
        print(_usage("todo", "from-main"))
        raise SystemExit(1)

    project_root = str(Path.cwd())
    try:
        output = create_from_main_skeleton(project_root, slug, description=description, all_files=all_files)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(output)


# ---------------------------------------------------------------------------
# Artifact and stamp handlers (todos.db backed)
# ---------------------------------------------------------------------------


def _handle_todo_artifacts(args: list[str]) -> None:
    """Handle telec todo artifacts {list|read|write} <slug> [<name>] [<content>]."""
    if not args:
        print("Usage: telec todo artifacts {list|read|write} <slug> [<name>] [<content>]")
        raise SystemExit(1)

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand == "list":
        _handle_artifacts_list(sub_args)
    elif subcommand == "read":
        _handle_artifacts_read(sub_args)
    elif subcommand == "write":
        _handle_artifacts_write(sub_args)
    else:
        print(f"Unknown artifacts subcommand: {subcommand}")
        print("Usage: telec todo artifacts {list|read|write} <slug> [<name>] [<content>]")
        raise SystemExit(1)


def _handle_artifacts_list(args: list[str]) -> None:
    """Handle telec todo artifacts list <slug>."""
    if not args or args[0].startswith("-"):
        print("Usage: telec todo artifacts list <slug>")
        raise SystemExit(1)

    slug = args[0]
    result = tool_api_request("GET", f"/todos/artifacts/{slug}")
    if isinstance(result, dict):
        artifacts = result.get("artifacts", [])
        if not artifacts:
            print(f"No artifacts for {slug}")
        else:
            for name in artifacts:
                print(f"  {name}")
    else:
        print(result)


def _handle_artifacts_read(args: list[str]) -> None:
    """Handle telec todo artifacts read <slug> <name>."""
    if len(args) < 2:
        print("Usage: telec todo artifacts read <slug> <name>")
        raise SystemExit(1)

    slug, name = args[0], args[1]
    result = tool_api_request("GET", f"/todos/artifacts/{slug}/{name}")
    if isinstance(result, dict):
        print(result.get("content", ""))
    else:
        print(result)


def _handle_artifacts_write(args: list[str]) -> None:
    """Handle telec todo artifacts write <slug> <name> <content>."""
    slug: str | None = None
    name: str | None = None
    content: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec todo artifacts write <slug> <name> <content>")
            raise SystemExit(1)
        elif slug is None:
            slug = arg
        elif name is None:
            name = arg
        elif content is None:
            content = arg
        else:
            print("Too many positional arguments.")
            print("Usage: telec todo artifacts write <slug> <name> <content>")
            raise SystemExit(1)
        i += 1

    if not slug or not name or not content:
        print("Usage: telec todo artifacts write <slug> <name> <content>")
        raise SystemExit(1)

    result = tool_api_request(
        "POST",
        f"/todos/artifacts/{slug}/{name}",
        json_body={"content": content, "cwd": str(Path.cwd())},
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Wrote {name} for {slug}")
    else:
        print(result)


def _handle_todo_stamp(args: list[str]) -> None:
    """Handle telec todo stamp <slug> --verdict|--build|--dor-score|--dor-status|--grounding-invalidated."""
    slug: str | None = None
    stamp_type: str | None = None
    value: str | None = None
    dor_score: str | None = None
    dor_status: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--verdict" and i + 1 < len(args):
            stamp_type = "verdict"
            value = args[i + 1]
            i += 2
        elif arg == "--build" and i + 1 < len(args):
            stamp_type = "build"
            value = args[i + 1]
            i += 2
        elif arg == "--dor-score" and i + 1 < len(args):
            dor_score = args[i + 1]
            i += 2
        elif arg == "--dor-status" and i + 1 < len(args):
            dor_status = args[i + 1]
            i += 2
        elif arg == "--grounding-invalidated":
            stamp_type = "grounding"
            value = "invalid"
            i += 1
        elif not arg.startswith("-"):
            slug = arg
            i += 1
        else:
            i += 1

    # Build compound DOR value from --dor-score and/or --dor-status
    if dor_score is not None or dor_status is not None:
        stamp_type = "dor"
        parts: list[str] = []
        if dor_score is not None:
            parts.append(f"score:{dor_score}")
        if dor_status is not None:
            parts.append(f"status:{dor_status}")
        value = ",".join(parts)

    if not slug:
        print("Usage: telec todo stamp <slug> --verdict approve|needs_work")
        raise SystemExit(1)
    if not stamp_type or not value:
        print("Missing stamp flag (--verdict, --build, --dor-score, --dor-status, --grounding-invalidated)")
        raise SystemExit(1)

    result = tool_api_request(
        "POST",
        f"/todos/stamp/{slug}",
        json_body={"stamp_type": stamp_type, "value": value, "cwd": str(Path.cwd())},
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Stamped {stamp_type}={value} for {slug}")
    else:
        print(result)


def _handle_todo_show(args: list[str]) -> None:
    """Handle telec todo show <slug> — display full todo state payload."""
    import json as _json  # pylint: disable=import-outside-toplevel

    if not args or args[0].startswith("-"):
        print("Usage: telec todo show <slug>")
        raise SystemExit(1)

    slug = args[0]
    result = tool_api_request("GET", f"/todos/{slug}/show")

    if isinstance(result, dict) and "slug" in result:
        print(_json.dumps(result, indent=2))
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(result)
