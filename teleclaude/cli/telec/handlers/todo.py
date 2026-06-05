"""Handlers for telec todo commands."""

from __future__ import annotations

import asyncio
import json as _json
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

from teleclaude.api_models import TodoDumpRequest
from teleclaude.cli.telec.handlers._todo_show import _handle_todo_show
from teleclaude.cli.telec.handlers.todo_list import _handle_todo_list
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import print_json, tool_api_call, tool_api_request
from teleclaude.cli.tool_commands import (
    handle_todo_design,
    handle_todo_integrate,
    handle_todo_prepare,
    handle_todo_set_deps,
    handle_todo_work,
)
from teleclaude.cli.tool_commands._receipt import poll_operation
from teleclaude.constants import ARTIFACT_INPUT, ARTIFACT_NAMES, ARTIFACT_NAMES_RETIRED, ARTIFACT_NAMES_WRITABLE
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.next_machine.git_ops import extract_referenced_paths, get_head_commit
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, LifecycleStage
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_io import mark_phase_state, reconcile_phase_state
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances
from teleclaude.events.producer import ensure_event_producer
from teleclaude.git import GitCommandError
from teleclaude.project_root import resolve_invocation_cwd, resolve_state_root
from teleclaude.session_identity import get_session_id
from teleclaude.slug import validate_slug
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TodoDumpKind

if TYPE_CHECKING:
    pass

__all__ = [
    "_handle_todo",
    "_handle_todo_artifacts",
    "_handle_todo_create",
    "_handle_todo_deliver",
    "_handle_todo_design",
    "_handle_todo_freeze",
    "_handle_todo_list",
    "_handle_todo_mark_phase",
    "_handle_todo_reconcile",
    "_handle_todo_remove",
    "_handle_todo_rename",
    "_handle_todo_show",
    "_handle_todo_split",
    "_handle_todo_stamp",
    "_handle_todo_unfreeze",
    "handle_mark_phase",
]


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
    except (ValueError, GitCommandError) as exc:
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


def _handle_todo_reconcile(args: list[str]) -> None:
    """Handle telec todo reconcile <slug> [--stage prepare|work]."""
    slug: str | None = None
    stage: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--stage" and i + 1 < len(args):
            stage = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "reconcile"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "reconcile"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print(_usage("todo", "reconcile"))
        raise SystemExit(1)

    if stage is not None and stage not in {member.value for member in LifecycleStage}:
        print(f"Unknown stage value: {stage!r}", file=sys.stderr)
        print("Valid stage values:", file=sys.stderr)
        for value in sorted(member.value for member in LifecycleStage):
            print(f"  {value}", file=sys.stderr)
        raise SystemExit(1)

    try:
        payload = reconcile_phase_state(str(resolve_invocation_cwd()), slug, stage)
    except (ValueError, GitCommandError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Reconciled {slug} lifecycle_phase={payload['lifecycle_phase']}")


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    if not args:
        print(_usage("todo"))
        return

    subcommand = args[0]
    handlers = {
        "artifacts": _handle_todo_artifacts,
        "co-create": _handle_todo_design,
        "create": _handle_todo_create,
        "deliver": _handle_todo_deliver,
        "design": _handle_todo_design,
        "freeze": _handle_todo_freeze,
        "integrate": handle_todo_integrate,
        "list": _handle_todo_list,
        "mark-phase": _handle_todo_mark_phase,
        "prepare": handle_todo_prepare,
        "reactivate": _handle_todo_reactivate,
        "reconcile": _handle_todo_reconcile,
        "remove": _handle_todo_remove,
        "rename": _handle_todo_rename,
        "set-deps": handle_todo_set_deps,
        "show": _handle_todo_show,
        "split": _handle_todo_split,
        "stamp": _handle_todo_stamp,
        "unfreeze": _handle_todo_unfreeze,
        "work": handle_todo_work,
    }
    handler = handlers.get(subcommand)
    if handler is None:
        print(f"Unknown todo subcommand: {subcommand}")
        print(_usage("todo"))
        raise SystemExit(1)
    handler(args[1:])


def _validate_slugs(*slugs: str | None) -> None:
    try:
        for slug in slugs:
            if slug is not None:
                validate_slug(slug)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1) from exc


def _resolve_todo_project_root() -> Path:
    return resolve_state_root(resolve_invocation_cwd())


def _run_db(project_root: Path, slug: str, method: str, **kwargs: object) -> object:
    async def _execute() -> object:
        db = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
        await db.initialize()
        try:
            fn = getattr(db, method)
            return await fn(slug, **kwargs)
        finally:
            await db.close()

    return asyncio.run(_execute())


def _handle_todo_freeze(args: list[str]) -> None:
    """Handle telec todo freeze <slug>."""
    if not args:
        print(_usage("todo", "freeze"))
        return

    slug: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "freeze"))
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed.")
            raise SystemExit(1)
        slug = arg
        i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "freeze"))
        raise SystemExit(1)

    _validate_slugs(slug)
    project_root = _resolve_todo_project_root()
    if _run_db(project_root, slug, "freeze"):
        print(f"Froze {slug} → icebox")
        return
    print(f"Slug not found in todo list: {slug}")
    raise SystemExit(1)


def _handle_todo_unfreeze(args: list[str]) -> None:
    """Handle telec todo unfreeze <slug>."""
    if not args:
        print(_usage("todo", "unfreeze"))
        return

    slug: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "unfreeze"))
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed.")
            raise SystemExit(1)
        slug = arg
        i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "unfreeze"))
        raise SystemExit(1)

    _validate_slugs(slug)
    project_root = _resolve_todo_project_root()
    if _run_db(project_root, slug, "unfreeze"):
        print(f"Unfroze {slug} → todo list")
        return
    print(f"Slug not found in icebox: {slug}")
    raise SystemExit(1)


def _handle_todo_deliver(args: list[str]) -> None:
    """Handle telec todo deliver <slug> [--commit SHA]."""
    if not args:
        print(_usage("todo", "deliver"))
        return

    slug: str | None = None
    commit: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--commit" and i + 1 < len(args):
            commit = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "deliver"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "deliver"))
        raise SystemExit(1)

    _validate_slugs(slug)
    project_root = _resolve_todo_project_root()
    if not _run_db(project_root, slug, "deliver", commit=commit):
        print(f"Slug not found in todo list: {slug}")
        raise SystemExit(1)

    cleanup_delivered_slug(str(project_root), slug)
    print(f"Delivered {slug} (cleanup complete)")


def _handle_todo_create(args: list[str]) -> None:
    """Handle telec todo create <slug> <content> --kind <kind> [--after <deps>] [--silent]."""
    slug: str | None = None
    content: str | None = None
    after: list[str] | None = None
    silent = False
    plan = False
    kind_value: str | None = None

    _VALID_KINDS_STR = "|".join(sorted(ALL_DUMP_KINDS))

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg == "--silent":
            silent = True
            i += 1
        elif arg == "--plan":
            plan = True
            i += 1
        elif arg == "--kind" and i + 1 < len(args):
            kind_value = args[i + 1]
            i += 2
        elif arg == "--kind":
            print(f"Error: --kind requires a value ({_VALID_KINDS_STR})")
            print(_usage("todo", "create"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "create"))
            raise SystemExit(1)
        else:
            if slug is None:
                slug = arg
            elif content is None:
                content = arg
            else:
                print("Too many positional arguments.")
                print(_usage("todo", "create"))
                raise SystemExit(1)
            i += 1

    if not slug:
        print(_usage("todo", "create"))
        raise SystemExit(1)

    if not content or not content.strip():
        print("Error: <content> is required and must not be empty")
        print(_usage("todo", "create"))
        raise SystemExit(1)

    if kind_value is None:
        print(f"Error: --kind is required. Valid values: {_VALID_KINDS_STR}")
        print(_usage("todo", "create"))
        raise SystemExit(1)

    if kind_value not in ALL_DUMP_KINDS:
        print(f"Error: invalid --kind '{kind_value}'. Valid values: {_VALID_KINDS_STR}")
        print(_usage("todo", "create"))
        raise SystemExit(1)

    dump_kind = cast(TodoDumpKind, kind_value)

    request = TodoDumpRequest(
        slug=slug,
        content=content,
        after=after,
        kind=dump_kind,
        cwd=str(resolve_invocation_cwd()),
        silent=silent,
        plan=plan,
    )
    result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body=request.model_dump(mode="json"),
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Created todo: {slug} (kind={dump_kind})")
    else:
        print(f"Error: unexpected response: {result}")
        raise SystemExit(1)


def _handle_todo_design(args: list[str]) -> None:
    """Handle telec todo design [<slug>]."""
    handle_todo_design(args)


def _handle_todo_split(args: list[str]) -> None:
    """Handle telec todo split <slug> --into <child1> [<child2> ...].

    Creates children in todos.db; parent becomes a stateless holder.
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
    """Handle telec todo remove — delete state, artifacts, and todo entry from todos.db.

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
        if _render_remove_refusal(status, slug):
            raise SystemExit(1)
        print(f"Error: {status['error']}", file=sys.stderr)
        raise SystemExit(1)
    else:
        print_json(status)
        raise SystemExit(1)


def _render_remove_refusal(status: dict[object, object], slug: str) -> bool:
    """Render structured remove-refusal operation payloads."""
    error_payload = status.get("error_payload")
    if not isinstance(error_payload, dict) or error_payload.get("kind") != "remove_refused_orphan":
        return False
    raw_blocking = error_payload.get("blocking_snippets")
    if not isinstance(raw_blocking, list):
        return False

    print("Remove refused; blocking snippets:", file=sys.stderr)
    rendered_count = 0
    for raw_snippet in raw_blocking:
        if not isinstance(raw_snippet, dict):
            continue
        path = raw_snippet.get("path")
        slug_role = raw_snippet.get("slug_role")
        live_count = raw_snippet.get("live_deliverer_count")
        if not isinstance(path, str) or not isinstance(slug_role, str) or not isinstance(live_count, int):
            continue
        print(
            f"- path={path} slug_role={slug_role} live_deliverer_count={live_count}",
            file=sys.stderr,
        )
        rendered_count += 1

    print(
        f"Refused: {slug} would orphan {rendered_count} snippet(s); see structured error above.",
        file=sys.stderr,
    )
    return True


def _handle_todo_rename(args: list[str]) -> None:
    """Handle telec todo rename <old-slug> <new-slug>."""
    if len(args) != 2 or any(arg.startswith("-") for arg in args):
        print(_usage("todo", "rename"))
        raise SystemExit(1)

    old_slug, new_slug = args
    body = {
        "old_slug": old_slug,
        "new_slug": new_slug,
        "cwd": str(resolve_invocation_cwd()),
        "client_request_id": str(uuid.uuid4()),
    }
    receipt: object = tool_api_call("POST", "/todos/rename", json_body=body)
    if not isinstance(receipt, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        print_json(receipt)
        raise SystemExit(1)

    status: object = poll_operation(receipt, estimated_timeout_ms=30_000)
    if isinstance(status, dict) and status.get("state") == "completed":  # pyright: ignore[reportUnnecessaryIsInstance]
        result = status.get("result")
        if isinstance(result, str) and result:
            print(result)
        else:
            print_json(status)
    elif isinstance(status, dict) and status.get("error"):  # pyright: ignore[reportUnnecessaryIsInstance]
        print(f"Error: {status['error']}", file=sys.stderr)
        raise SystemExit(1)
    else:
        print_json(status)
        raise SystemExit(1)


# Artifact and stamp handlers (consolidated back from _todo_extra.py)
# ---------------------------------------------------------------------------


def _validate_artifact_name(name: str) -> None:
    """Refuse unknown artifact names."""
    if name not in ARTIFACT_NAMES:
        print(f"Unknown artifact kind: {name}", file=sys.stderr)
        print(f"Valid kinds: {', '.join(sorted(ARTIFACT_NAMES))}", file=sys.stderr)
        raise SystemExit(1)


def _validate_artifact_name_write(name: str) -> None:
    """Refuse retired or read-only artifact names for writes."""
    if name not in ARTIFACT_NAMES_WRITABLE:
        if name in ARTIFACT_NAMES_RETIRED:
            print(f"Artifact kind '{name}' is retired (read-only).", file=sys.stderr)
        else:
            print(f"Unknown artifact kind: {name}", file=sys.stderr)
        print(f"Writable kinds: {', '.join(sorted(ARTIFACT_NAMES_WRITABLE))}", file=sys.stderr)
        raise SystemExit(1)


def _handle_todo_artifacts(args: list[str]) -> None:
    """Handle telec todo artifacts {list|read|write|diff|remove}."""
    if not args:
        print("Usage: telec todo artifacts {list|read|write|diff|remove} <slug> [<name>] [<content>|<old>] [<new>]")
        raise SystemExit(1)

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand == "list":
        _handle_artifacts_list(sub_args)
    elif subcommand == "read":
        _handle_artifacts_read(sub_args)
    elif subcommand == "write":
        _handle_artifacts_write(sub_args)
    elif subcommand == "diff":
        _handle_artifacts_diff(sub_args)
    elif subcommand == "remove":
        _handle_artifacts_remove(sub_args)
    else:
        print(f"Unknown artifacts subcommand: {subcommand}")
        print("Usage: telec todo artifacts {list|read|write|diff|remove} <slug> [<name>] [<content>|<old>] [<new>]")
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
    _validate_artifact_name(name)
    result = tool_api_request("GET", f"/todos/artifacts/{slug}/{name}")
    if isinstance(result, dict):
        print(result.get("content", ""))
    else:
        print(result)


def _handle_artifacts_diff(args: list[str]) -> None:
    """Handle telec todo artifacts diff <slug> <name> <old-digest> <new-digest>."""
    if len(args) < 4:
        print("Usage: telec todo artifacts diff <slug> <name> <old-digest> <new-digest>")
        raise SystemExit(1)

    slug, name, old_digest, new_digest = args[0], args[1], args[2], args[3]
    _validate_artifact_name(name)
    result = tool_api_request(
        "GET",
        f"/todos/artifacts/{slug}/{name}/diff",
        params={"old": old_digest, "new": new_digest, "cwd": str(resolve_invocation_cwd())},
    )
    if isinstance(result, dict):
        print(result.get("diff", ""))
    else:
        print(result)
        raise SystemExit(1)


def _handle_artifacts_remove(args: list[str]) -> None:
    """Handle telec todo artifacts remove <slug> <name>."""
    slug_val: str | None = None
    name_val: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec todo artifacts remove <slug> <name>")
            raise SystemExit(1)
        if slug_val is None:
            slug_val = arg
        elif name_val is None:
            name_val = arg
        else:
            print("Too many positional arguments.")
            print("Usage: telec todo artifacts remove <slug> <name>")
            raise SystemExit(1)
        i += 1

    if not slug_val or not name_val:
        print("Usage: telec todo artifacts remove <slug> <name>")
        raise SystemExit(1)

    _validate_artifact_name(name_val)
    if name_val == ARTIFACT_INPUT:
        print("input artifact cannot be removed")
        raise SystemExit(1)

    result = tool_api_request(
        "DELETE",
        f"/todos/artifacts/{slug_val}/{name_val}",
        params={"cwd": str(resolve_invocation_cwd())},
    )
    if not isinstance(result, dict) or result.get("status") != "ok":
        print(result)
        raise SystemExit(1)

    if result.get("removed") is True:
        versions_deleted = result.get("versions_deleted", 0)
        print(f"Removed {name_val} for {slug_val}; deleted {versions_deleted} version rows.")
    else:
        print(f"No {name_val} artifact for {slug_val}; nothing needed to be removed.")


def _handle_artifacts_write(args: list[str]) -> None:
    """Handle telec todo artifacts write <slug> <name> <content>."""
    slug_val: str | None = None
    name_val: str | None = None
    content_val: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec todo artifacts write <slug> <name> <content>")
            raise SystemExit(1)
        elif slug_val is None:
            slug_val = arg
        elif name_val is None:
            name_val = arg
        elif content_val is None:
            content_val = arg
        else:
            print("Too many positional arguments.")
            print("Usage: telec todo artifacts write <slug> <name> <content>")
            raise SystemExit(1)
        i += 1

    if not slug_val or not name_val or not content_val:
        print("Usage: telec todo artifacts write <slug> <name> <content>")
        raise SystemExit(1)

    _validate_artifact_name_write(name_val)
    cwd = str(resolve_invocation_cwd())
    result = tool_api_request(
        "POST",
        f"/todos/artifacts/{slug_val}/{name_val}",
        json_body={
            "content": content_val,
            "cwd": cwd,
            "codebase_sha_at_write": get_head_commit(cwd),
            "referenced_paths": extract_referenced_paths(content_val, cwd),
        },
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Wrote {name_val} for {slug_val}")
    else:
        print(result)


def _handle_todo_stamp(args: list[str]) -> None:
    """Handle telec todo stamp."""
    for arg in args:
        if arg == "--build-started":
            print("--build-started is machine-owned; run telec todo work <slug> to enter build.")
            raise SystemExit(1)

    slug, stamp_type, value, phase = _parse_todo_stamp_args(args)

    if not slug:
        print("Usage: telec todo stamp <slug> --verdict approve --phase <phase>")
        raise SystemExit(1)
    if not stamp_type:
        print(
            "Missing stamp flag (--verdict, --prd-approved, --architecture-skipped, "
            "--drift-reviewed, --build-complete, "
            "--finalize-ready, --deferrals-processed, --design-spec-confirmed, "
            "--art-approved, --visuals-approved)"
        )
        raise SystemExit(1)
    if stamp_type == "verdict" and not phase:
        print("--verdict requires --phase <phase>")
        raise SystemExit(1)

    if stamp_type == "finalize_ready":
        ensure_event_producer()

    async def _apply_stamp() -> None:
        try:
            await apply_todo_stamp(
                cwd=str(resolve_invocation_cwd()),
                slug=slug,
                stamp_type=stamp_type,
                value=value or "",
                phase=phase,
                caller_session_id=get_session_id(),
            )
        finally:
            await close_todos_db_instances()

    try:
        asyncio.run(_apply_stamp())
    except (PermissionError, ValueError, RuntimeError, GitCommandError, StateMutationError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    label = f"{stamp_type}={value}" if value else stamp_type
    if phase:
        label = f"{label} phase={phase}"
    print(f"Stamped {label} for {slug}")


def _parse_todo_stamp_args(args: list[str]) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse ``telec todo stamp`` argv into slug, stamp type, value, and phase."""
    slug: str | None = None
    stamp_type: str | None = None
    value: str | None = None
    phase: str | None = None

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
        elif arg in _STAMP_BOOLEAN_FLAGS:
            stamp_type = _STAMP_BOOLEAN_FLAGS[arg]
            value = "true"
            i += 1
        elif arg in _STAMP_REASON_FLAGS and i + 1 < len(args):
            stamp_type = _STAMP_REASON_FLAGS[arg]
            value = args[i + 1]
            i += 2
        elif arg == "--drift-reviewed" and i + 3 < len(args):
            stamp_type = "drift_reviewed"
            value = _json.dumps({"artifact": args[i + 1], "verdict": args[i + 2], "reason": args[i + 3]})
            i += 4
        elif arg == "--finalize-ready":
            stamp_type = "finalize_ready"
            value = ""
            i += 1
        elif not arg.startswith("-"):
            slug = arg
            i += 1
        else:
            i += 1

    return slug, stamp_type, value, phase


_STAMP_BOOLEAN_FLAGS = {
    "--prd-approved": "prd_approved",
    "--requirements-ready": "requirements_ready",
    "--plan-ready": "plan_ready",
    "--deferrals-processed": "deferrals_processed",
    "--design-spec-confirmed": "creative_design_spec_confirmed",
    "--art-approved": "creative_art_approved",
    "--visuals-approved": "creative_visuals_approved",
    "--build-complete": "build_complete",
}

_STAMP_REASON_FLAGS = {
    "--architecture-skipped": "architecture_skipped",
}


# ── Reactivate handler ─────────────────────────────────────────────────────
# _handle_todo_show is imported from _todo_show.py (combines --include-removed
# and --include-artifact-content per the enrich-todo-show-payload merge).


def _handle_todo_reactivate(args: list[str]) -> None:
    """Handle telec todo reactivate <slug> — restore a soft-removed todo."""
    if not args or args[0].startswith("-"):
        print("Usage: telec todo reactivate <slug>")
        raise SystemExit(1)

    slug = args[0]
    result = tool_api_request("POST", f"/todos/{slug}/reactivate")

    if isinstance(result, dict) and result.get("slug"):
        print(f"Restored todo: {result['slug']}")
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(result)
