"""Handlers for telec todo commands."""

from __future__ import annotations

import json as _json
import shlex
import sys
import uuid
from typing import Literal

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDumpRequest
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import print_json, tool_api_call, tool_api_request
from teleclaude.cli.tool_commands import (
    handle_todo_create,
    handle_todo_integrate,
    handle_todo_prepare,
    handle_todo_set_deps,
    handle_todo_work,
)
from teleclaude.cli.tool_commands._receipt import poll_operation
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.state_io import mark_phase_state
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.resource_validation import validate_all_todos, validate_todo
from teleclaude.todo_scaffold import create_from_main_skeleton

__all__ = [
    "_handle_todo",
    "_handle_todo_artifacts",
    "_handle_todo_dump",
    "_handle_todo_from_main",
    "_handle_todo_mark_phase",
    "_handle_todo_mark_ready",
    "_handle_todo_remove",
    "_handle_todo_show",
    "_handle_todo_split",
    "_handle_todo_stamp",
    "_handle_todo_validate",
    "handle_mark_phase",
]


def _handle_todo_mark_ready(args: list[str]) -> None:
    """Handle telec todo mark-ready <slug> [<slug> ...].

    Fast-track one or more TODOs to work-ready state by delegating to mark-phase
    with ``prepared``.
    """
    if not args:
        print("Usage: telec todo mark-ready <slug> [<slug> ...]")
        raise SystemExit(1)

    slugs = [a for a in args if not a.startswith("-")]
    if not slugs:
        print("Missing required argument: <slug>")
        raise SystemExit(1)

    cwd = str(resolve_invocation_cwd())
    failed = 0
    for slug in slugs:
        rc = handle_mark_phase(slug, "prepared", cwd)
        if rc == 0:
            print(f"✓ {slug} fast-tracked to work-ready (prepared)")
        else:
            failed += 1

    if failed:
        raise SystemExit(1)


def handle_mark_phase(slug: str, phase: str, cwd: str) -> int:
    """Operator override: set the canonical lifecycle phase."""
    lifecycle_values = {p.value for p in LifecyclePhase}
    if phase not in lifecycle_values:
        prepare_values = {p.value for p in PreparePhase}
        work_values = {p.value for p in WorkPhase}
        print(f"Unknown phase value: {phase!r}", file=sys.stderr)
        print("Valid lifecycle_phase values:", file=sys.stderr)
        for value in sorted(lifecycle_values):
            print(f"  {value}", file=sys.stderr)
        print("Legacy prepare_phase values:", file=sys.stderr)
        for value in sorted(prepare_values):
            print(f"  {value}", file=sys.stderr)
        print("Legacy work_phase values:", file=sys.stderr)
        for value in sorted(work_values):
            print(f"  {value}", file=sys.stderr)
        return 1

    try:
        mark_phase_state(cwd, slug, phase)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Marked {slug} lifecycle_phase={phase}")
    return 0


def _handle_todo_mark_phase(args: list[str]) -> None:
    """Handle telec todo mark-phase <slug> --phase <value>.

    Thin argv adapter over :func:`handle_mark_phase`.
    """
    slug: str | None = None
    phase: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--phase" and i + 1 < len(args):
            phase = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "mark-phase"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "mark-phase"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug or not phase:
        print(_usage("todo", "mark-phase"))
        raise SystemExit(1)

    exit_code = handle_mark_phase(slug=slug, phase=phase, cwd=str(resolve_invocation_cwd()))
    if exit_code != 0:
        raise SystemExit(exit_code)


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
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
    elif subcommand == "set-deps":
        handle_todo_set_deps(args[1:])
    elif subcommand == "dump":
        _handle_todo_dump(args[1:])
    elif subcommand == "split":
        _handle_todo_split(args[1:])
    elif subcommand == "mark-ready":
        _handle_todo_mark_ready(args[1:])
    elif subcommand == "mark-phase":
        _handle_todo_mark_phase(args[1:])
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

    slug: str | None = None
    project_root = resolve_invocation_cwd()

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


def _handle_todo_dump(args: list[str]) -> None:
    """Handle telec todo dump <slug> <content> [--after <deps>] [--draft] [--prepped].

    Creates a todo in todos.db: state, artifact row, and roadmap entry. Everything
    lives in the database — no filesystem writes, no git commits.

    Modes:
      - Default: writes content as the "input" artifact; enters the normal prepare
        lifecycle.
      - --draft: same as default but suppresses the todo_dumped notification.
      - --prepped: writes content as the "implementation-plan" artifact and marks the
        todo as kind=prepped, immediately ready for build. Skips the prepare phase.
    """
    if len(args) < 2:
        print(_usage("todo", "dump"))
        raise SystemExit(1)

    slug: str | None = None
    content: str | None = None
    after: list[str] | None = None
    draft = False
    prepped = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg == "--draft":
            draft = True
            i += 1
        elif arg == "--prepped":
            prepped = True
            i += 1
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

    # Resolve the lifecycle-router lane for this dump. The CLI stamps this as
    # the first-class ``kind`` on the todo_dumped event so the lifecycle
    # router can dispatch from payload alone, without re-reading todo state.
    event_kind = "prepped" if prepped else "todo"

    # Create via daemon API — writes state + artifact + roadmap entry to todos.db.
    # When --prepped, kind="prepped" routes the server-side dump to write the content
    # as the implementation-plan artifact and stamp the todo as ready for build.
    # Determine the kind for the API request: draft and prepped are explicit
    # lanes; default (None) enters the normal prepare lifecycle.
    dump_kind: Literal["bug", "draft", "prepped"] | None = None
    if draft:
        dump_kind = "draft"
    elif prepped:
        dump_kind = "prepped"

    request = TodoDumpRequest(
        slug=slug,
        content=content,
        after=after,
        kind=dump_kind,
        cwd=str(resolve_invocation_cwd()),
    )
    result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body=request.model_dump(mode="json"),
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Dumped todo: {slug}" + (" (prepped, ready for build)" if prepped else ""))
    else:
        print(f"Error: unexpected response: {result}")
        raise SystemExit(1)

    if draft:
        return

    # Emit planning.todo_dumped notification
    _log = get_logger(__name__)
    try:
        envelope = EventEnvelope(
            event="domain.software-development.planning.todo_dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=f"Todo dumped: {slug}",
            payload={"slug": slug, "kind": event_kind, "project_root": str(resolve_invocation_cwd())},
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
        json_body={"slug": slug, "children": children, "cwd": str(resolve_invocation_cwd())},
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

    body = {
        "slug": slug,
        "cwd": str(resolve_invocation_cwd()),
        "client_request_id": str(uuid.uuid4()),
    }
    receipt: object = tool_api_call("POST", "/todos/remove", json_body=body)
    if not isinstance(receipt, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        print_json(receipt)
        raise SystemExit(1)

    status: object = poll_operation(receipt, estimated_timeout_ms=30_000)
    if isinstance(status, dict) and status.get("state") == "completed":  # pyright: ignore[reportUnnecessaryIsInstance]
        print(f"Removed todo: {slug}")
    elif isinstance(status, dict) and status.get("error"):  # pyright: ignore[reportUnnecessaryIsInstance]
        print(f"Error: {status['error']}", file=sys.stderr)
        raise SystemExit(1)
    else:
        print_json(status)
        raise SystemExit(1)


def _handle_todo_from_main(args: list[str]) -> None:
    """Handle telec todo from-main --slug <name> [--description <desc>] [--all]."""
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

    project_root = str(resolve_invocation_cwd())
    try:
        output = create_from_main_skeleton(project_root, slug, description=description, all_files=all_files)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(output)

    _log = get_logger(__name__)
    try:
        envelope = EventEnvelope(
            event="domain.software-development.planning.todo_dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=f"Todo scaffolded from main: {slug}",
            payload={"slug": slug, "kind": "built", "project_root": project_root},
        )
        tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
    except Exception:
        _log.warning("Todo scaffolded from main but notification emission failed: %s", slug)
        recovery_command = (
            "telec sessions run --command /next-work "
            f"--args {shlex.quote(slug)} --project {shlex.quote(project_root)} --detach"
        )
        print(
            "Warning: worker handoff did not start automatically. "
            f"Run this command to continue manually:\n{recovery_command}",
            file=sys.stderr,
        )


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
        json_body={"content": content, "cwd": str(resolve_invocation_cwd())},
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Wrote {name} for {slug}")
    else:
        print(result)


def _handle_todo_stamp(args: list[str]) -> None:
    """Handle telec todo stamp.

    Supported flag combinations:
      --verdict <approve|changes_requested|needs_work|needs_decision> --phase <phase>
      --dor-score <n> [--dor-status <s>]
      --dor-status <s>
      --requirements-ready
      --grounding-invalidated
      --specs-built
      --plan-ready
      --build-started
      --build-complete
      --finalize-ready
    """
    slug, stamp_type, value, phase = _parse_todo_stamp_args(args)

    if not slug:
        print("Usage: telec todo stamp <slug> --verdict approve --phase <phase>")
        raise SystemExit(1)
    if not stamp_type:
        print(
            "Missing stamp flag (--verdict, --dor-score, --dor-status, "
            "--requirements-ready, --grounding-invalidated, --specs-built, "
            "--plan-ready, --build-started, --build-complete, --finalize-ready)"
        )
        raise SystemExit(1)
    if stamp_type == "verdict" and not phase:
        print("--verdict requires --phase <phase>")
        raise SystemExit(1)

    body: dict[str, str] = {
        "stamp_type": stamp_type,
        "value": value or "",
        "cwd": str(resolve_invocation_cwd()),
    }
    if phase:
        body["phase"] = phase

    result = tool_api_request(
        "POST",
        f"/todos/stamp/{slug}",
        json_body=body,
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        label = f"{stamp_type}={value}" if value else stamp_type
        if phase:
            label = f"{label} phase={phase}"
        print(f"Stamped {label} for {slug}")
    else:
        print(result)


def _parse_todo_stamp_args(args: list[str]) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse ``telec todo stamp`` argv into slug, stamp type, value, and phase."""
    slug: str | None = None
    stamp_type: str | None = None
    value: str | None = None
    phase: str | None = None
    dor_score: str | None = None
    dor_status: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--verdict" and i + 1 < len(args):
            stamp_type = "verdict"
            value = args[i + 1]
            i += 2
        elif arg == "--phase" and i + 1 < len(args):
            phase = args[i + 1]
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
        elif arg == "--requirements-ready":
            stamp_type = "requirements_ready"
            value = ""
            i += 1
        elif arg == "--specs-built":
            stamp_type = "specs_built"
            value = "true"
            i += 1
        elif arg == "--plan-ready":
            stamp_type = "plan_ready"
            value = ""
            i += 1
        elif arg == "--build-started":
            stamp_type = "build_started"
            value = ""
            i += 1
        elif arg == "--build-complete":
            stamp_type = "build_complete"
            value = ""
            i += 1
        elif arg == "--finalize-ready":
            stamp_type = "finalize_ready"
            value = ""
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

    return slug, stamp_type, value, phase


def _handle_todo_show(args: list[str]) -> None:
    """Handle telec todo show <slug> — display full todo state payload."""
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
