"""Handlers for telec todo commands."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._creation_gate import render_todo_creation_gate
from teleclaude.cli.telec.handlers._todo_read import run_todo_read
from teleclaude.cli.telec.handlers._todo_show import _handle_todo_show
from teleclaude.cli.telec.handlers._todo_stamp import _handle_todo_stamp
from teleclaude.cli.telec.handlers.todo_list import _handle_todo_list, _resolve_project_root_or_exit
from teleclaude.cli.telec.handlers.todo_remove import render_remove_refusal
from teleclaude.cli.telec.handlers.todo_update_args import _parse_todo_update_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import TODO_CREATE, TODO_DELIVER, TODO_REACTIVATE, TODO_REMOVE
from teleclaude.constants import (
    ARTIFACT_INPUT,
    ARTIFACT_NAMES,
    ARTIFACT_NAMES_RETIRED,
    ARTIFACT_NAMES_WRITABLE,
    SLUG_NOT_FOUND_DETAIL,
    SLUG_NOT_IN_ICEBOX_DETAIL,
)
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.slug import validate_slug
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TODO_KIND_USAGE, TodoDumpKind
from teleclaude.types.todos import DependencyEntry

if TYPE_CHECKING:
    from teleclaude.core.todos_db import (
        ArtifactWritersRow,
        TodosDb,
    )


class _TodoUpdateBody(TypedDict):
    slug: str
    cwd: str
    client_request_id: str
    new_slug: NotRequired[str]
    after: NotRequired[list[str]]
    schedule: NotRequired[str]
    kind: NotRequired[str]
    force: NotRequired[bool]
    hold: NotRequired[bool]
    reason: NotRequired[str]
    release: NotRequired[bool]
    unclaim: NotRequired[bool]


_CREATION_ACK_FLAG = "--approved"
_REASON_REQUIRED_WITH_HOLD = "Error: --reason is required with --hold"
_REASON_REQUIRES_HOLD = "Error: --reason is valid only with --hold"
_UNKNOWN_TODO_SUBCOMMAND_TEMPLATE = "Unknown todo subcommand: {subcommand}"

_TODO_CREATION_GATE = render_todo_creation_gate(_CREATION_ACK_FLAG)


@dataclass(frozen=True)
class _ParsedTodoCreate:
    slug: str | None
    content: str | None
    after: list[str] | None
    schedule: str | None
    icebox: bool
    group: str | None
    project_root: str | None
    plan: bool
    hold: bool
    reason: str | None
    human_involvement_reason: str | None
    kind_value: str | None
    approved: bool


class _TodoSubcommand(StrEnum):
    """Closed vocabulary for todo subcommands routed by this handler."""

    ARTIFACTS = "artifacts"
    CREATE = "create"
    DELIVER = "deliver"
    DESIGN = "design"
    FREEZE = "freeze"
    INTEGRATE = "integrate"
    LIST = "list"
    PREPARE = "prepare"
    REACTIVATE = "reactivate"
    REMOVE = "remove"
    SHOW = "show"
    STAMP = "stamp"
    UNFREEZE = "unfreeze"
    UPDATE = "update"
    WORK = "work"


__all__ = [
    "_handle_todo",
    "_handle_todo_artifacts",
    "_handle_todo_create",
    "_handle_todo_deliver",
    "_handle_todo_design",
    "_handle_todo_freeze",
    "_handle_todo_list",
    "_handle_todo_remove",
    "_handle_todo_show",
    "_handle_todo_stamp",
    "_handle_todo_unfreeze",
    "_handle_todo_update",
]


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    if not args:
        print(_usage("todo"))
        return

    try:
        subcommand = _TodoSubcommand(args[0])
    except ValueError:
        print(_UNKNOWN_TODO_SUBCOMMAND_TEMPLATE.format(subcommand=args[0]))
        print(_usage("todo"))
        raise SystemExit(1) from None
    handler = _TODO_SUBCOMMAND_HANDLERS.get(subcommand)
    if handler is None:
        print(_UNKNOWN_TODO_SUBCOMMAND_TEMPLATE.format(subcommand=subcommand.value))
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


def _run_db(project_root: Path, slug: str, method: str, **kwargs: object) -> object:
    from teleclaude.core.todos_db import TodosDb  # noqa: PLC0415 - deferred command-local dependency.

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
    from teleclaude.core.todo_dependency_warnings import (  # noqa: PLC0415 - only freeze reads dependent warning state.
        freeze_dependent_warnings,
    )

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
    project_root = _resolve_project_root_or_exit()
    if _run_db(project_root, slug, "freeze"):
        print(f"Froze {slug} → icebox")
        open_dependents = cast(list[str], _run_db(project_root, slug, "get_open_dependents"))
        for warning in freeze_dependent_warnings(slug, open_dependents):
            print(warning)
        return
    print(SLUG_NOT_FOUND_DETAIL.format(slug=slug))
    raise SystemExit(1)


def _handle_todo_unfreeze(args: list[str]) -> None:
    """Handle telec todo unfreeze <slug>."""
    from teleclaude.core.todo_dependency_warnings import (  # noqa: PLC0415 - only unfreeze reads dependent warning state.
        unfreeze_frozen_dep_warnings,
    )

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
    project_root = _resolve_project_root_or_exit()
    if _run_db(project_root, slug, "unfreeze"):
        print(f"Unfroze {slug} → todo list")
        dependencies = cast(list[DependencyEntry], _run_db(project_root, slug, "get_deps_with_status"))
        for warning in unfreeze_frozen_dep_warnings(slug, dependencies):
            print(warning)
        return
    print(SLUG_NOT_IN_ICEBOX_DETAIL.format(slug=slug))
    raise SystemExit(1)


def _handle_todo_deliver(args: list[str]) -> None:
    """Handle telec todo deliver <slug> [--commit SHA]."""
    from teleclaude.core.next_machine.delivery import (  # noqa: PLC0415 - delivery owns lifecycle cleanup.
        cleanup_delivered_slug,
    )
    from teleclaude.core.next_machine.marker_reconciliation import (  # noqa: PLC0415 - deferred command-local dependency.
        MarkerMoment,
        reconcile_lifecycle_markers,
    )
    from teleclaude.core.todos_db._errors import (  # noqa: PLC0415 - delivery is the only handler for this refusal.
        DeliveryProvenanceRefused,
    )

    if not args:
        print(_usage("todo", "deliver"))
        return

    parsed = parse_command_args(TODO_DELIVER, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one slug is allowed.")
        raise SystemExit(1)
    slug = positionals[0] if positionals else None
    commit = parsed.value(F.FLAG_TODO_DELIVER_COMMIT)

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "deliver"))
        raise SystemExit(1)

    _validate_slugs(slug)
    project_root = _resolve_project_root_or_exit()
    receipt = reconcile_lifecycle_markers(project_root, slug, MarkerMoment.DELIVER)
    if not receipt.succeeded:
        print(f"Delivery reconciliation failed for {slug}: {receipt.reason}")
        raise SystemExit(1)
    try:
        delivered = _run_db(
            project_root,
            slug,
            "deliver",
            reconciliation_receipt=receipt,
            reconciliation_root=project_root,
            commit=commit,
        )
    except DeliveryProvenanceRefused as exc:
        kind = exc.kind or "unknown"
        print(f"Delivery refused for {exc.slug}: --commit is required for {kind} todos.")
        raise SystemExit(1) from exc
    if not delivered:
        print(SLUG_NOT_FOUND_DETAIL.format(slug=slug))
        raise SystemExit(1)

    cleanup_delivered_slug(str(project_root), slug)
    print(f"Delivered {slug} (cleanup complete)")


def _parse_todo_create_args(args: list[str]) -> _ParsedTodoCreate:
    parsed = parse_command_args(TODO_CREATE, args)
    positionals = parsed.positionals
    if len(positionals) > 2:
        print("Too many positional arguments.")
        print(_usage("todo", "create"))
        raise SystemExit(1)
    slug = positionals[0] if positionals else None
    content = positionals[1] if len(positionals) > 1 else None

    after_raw = parsed.values(F.FLAG_AFTER_DEPS)
    after = [part.strip() for raw in after_raw for part in raw.split(",") if part.strip()] if after_raw else None

    return _ParsedTodoCreate(
        slug=slug,
        content=content,
        after=after,
        schedule=parsed.value(F.FLAG_TODO_SCHEDULE),
        icebox=parsed.has(F.FLAG_TODO_ICEBOX),
        group=parsed.value(F.FLAG_TODO_GROUP),
        project_root=parsed.value(F.FLAG_TODO_PROJECT_ROOT),
        plan=parsed.has(F.FLAG_TODO_PLAN),
        hold=parsed.has(F.FLAG_TODO_CREATE_HOLD),
        reason=parsed.value(F.FLAG_TODO_CREATE_REASON),
        human_involvement_reason=parsed.value(F.FLAG_HUMAN_INVOLVED),
        kind_value=parsed.value(F.FLAG_TODO_KIND),
        approved=parsed.has(F.FLAG_TODO_CREATE_APPROVED),
    )


def _handle_todo_create(args: list[str]) -> None:
    from teleclaude.api_models import TodoDumpRequest  # noqa: PLC0415 - deferred command-local dependency.
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - deferred command-local dependency.

    parsed = _parse_todo_create_args(args)
    _VALID_KINDS_STR = TODO_KIND_USAGE

    slug = parsed.slug
    content = parsed.content
    if not slug:
        print(_usage("todo", "create"))
        raise SystemExit(1)

    if not content or not content.strip():
        print("Error: <content> is required and must not be empty")
        print(_usage("todo", "create"))
        raise SystemExit(1)
    if parsed.hold != (parsed.reason is not None) or (parsed.reason is not None and not parsed.reason.strip()):
        print(_REASON_REQUIRED_WITH_HOLD if parsed.hold else _REASON_REQUIRES_HOLD)
        raise SystemExit(1)

    # The interrogation gate: a complete creation request without the
    # acknowledgment flag is the designed discovery moment (mirrors the bug
    # filing gate) - serving it is the successful outcome, so this exits 0
    # and creates nothing. The gate verifies the pre-creation decisions were
    # faced, never that the answers are true.
    if not parsed.approved:
        print(_TODO_CREATION_GATE, file=sys.stderr, end="")
        return

    if parsed.kind_value is not None and parsed.kind_value not in ALL_DUMP_KINDS:
        print(f"Error: invalid --kind '{parsed.kind_value}'. Valid values: {_VALID_KINDS_STR}")
        print(_usage("todo", "create"))
        raise SystemExit(1)
    dump_kind = cast(TodoDumpKind, parsed.kind_value) if parsed.kind_value is not None else None

    request = TodoDumpRequest(
        slug=slug,
        content=content,
        after=parsed.after,
        schedule=parsed.schedule,
        kind=dump_kind,
        cwd=parsed.project_root if parsed.project_root is not None else str(resolve_invocation_cwd()),
        icebox=parsed.icebox,
        group=parsed.group,
        plan=parsed.plan,
        hold=parsed.hold,
        reason=parsed.reason.strip() if parsed.reason is not None else None,
        human_involved=parsed.human_involvement_reason is not None,
        human_involvement_reason=parsed.human_involvement_reason,
    )
    result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body=request.model_dump(mode="json"),
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        if dump_kind is None:
            print(f"Created todo: {slug}")
        else:
            print(f"Created todo: {slug} (kind={dump_kind})")
        if not parsed.icebox and not parsed.hold:
            print("Dispatched to the coordinator. Do not offer, ask about, or narrate further action on this todo.")
        warnings = result.get("warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if isinstance(warning, str):
                    print(warning)
    else:
        print(f"Error: unexpected response: {result}")
        raise SystemExit(1)


def _handle_todo_design(args: list[str]) -> None:
    """Handle telec todo design [<slug>]."""
    from teleclaude.cli.tool_commands.todo import handle_todo_design  # noqa: PLC0415 - defer this tool handler.

    handle_todo_design(args)


def _handle_todo_integrate(args: list[str]) -> None:
    """Handle telec todo integrate <slug>."""
    from teleclaude.cli.tool_commands.todo import handle_todo_integrate  # noqa: PLC0415 - defer this tool handler.

    handle_todo_integrate(args)


def _handle_todo_prepare(args: list[str]) -> None:
    """Handle telec todo prepare <slug>."""
    from teleclaude.cli.tool_commands.todo import handle_todo_prepare  # noqa: PLC0415 - defer this tool handler.

    handle_todo_prepare(args)


def _handle_todo_work(args: list[str]) -> None:
    """Handle telec todo work [<slug>]."""
    from teleclaude.cli.tool_commands.todo import handle_todo_work  # noqa: PLC0415 - defer this tool handler.

    handle_todo_work(args)


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove — delete state, artifacts, and todo entry from todos.db.

    Also cleans up worktree and branch if they exist.
    """
    from teleclaude.cli.tool_client import (  # noqa: PLC0415 - deferred command-local dependency.
        print_json,
        tool_api_call,
    )
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - receipt polling is used by remove/update only.
        poll_operation,
    )

    if not args:
        print(_usage("todo", "remove"))
        raise SystemExit(1)

    parsed = parse_command_args(TODO_REMOVE, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one slug is allowed.")
        print(_usage("todo", "remove"))
        raise SystemExit(1)
    slug = positionals[0] if positionals else None
    force = parsed.has(F.FLAG_TODO_REMOVE_FORCE)

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "remove"))
        raise SystemExit(1)

    body = {
        "slug": slug,
        "force": force,
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
        if render_remove_refusal(status, slug):
            raise SystemExit(1)
        print(f"Error: {status['error']}", file=sys.stderr)
        raise SystemExit(1)
    else:
        print_json(status)
        raise SystemExit(1)


def _normalize_after_values(raw_values: list[str]) -> list[str]:
    """Normalize raw --after CLI values into a validated slug list.

    Accepts CSV per value and repeated flags. ``--after ""`` is the explicit
    clear: returns ``[]``. Mixed empty/non-empty input and empty CSV segments
    are rejected with SystemExit(1).
    """
    empty_count = sum(1 for v in raw_values if not v.strip())
    non_empty_count = len(raw_values) - empty_count

    if empty_count and non_empty_count:
        print("Cannot mix empty --after with non-empty --after values.")
        raise SystemExit(1)

    if empty_count:
        return []

    normalized: list[str] = []
    for raw in raw_values:
        segments = [s.strip() for s in raw.split(",")]
        for seg in segments:
            if not seg:
                print(f"Empty segment in --after value: {raw!r}")
                raise SystemExit(1)
            normalized.append(seg)
    return normalized


def _handle_todo_update(args: list[str]) -> None:
    from teleclaude.cli.tool_client import (  # noqa: PLC0415 - deferred command-local dependency.
        print_json,
        tool_api_call,
    )
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - receipt polling is used by remove/update only.
        poll_operation,
    )

    parsed = _parse_todo_update_args(args)
    slug = parsed["slug"]
    new_slug = parsed["new_slug"]
    after_present = parsed["after_present"]
    kind = parsed["kind"]
    schedule = parsed["schedule"]
    force = parsed["force"]
    hold = parsed["hold"]
    reason = parsed["reason"]
    release = parsed["release"]
    unclaim = parsed["unclaim"]
    after = _normalize_after_values(parsed["raw_after"]) if after_present else []

    _validate_slugs(slug, new_slug, *after)
    if kind is not None and kind not in ALL_DUMP_KINDS:
        print(f"unknown todo kind: {kind!r}")
        print(f"Valid kinds: {TODO_KIND_USAGE}")
        raise SystemExit(1)
    if hold and release:
        print("--hold and --release are mutually exclusive")
        raise SystemExit(1)
    if hold != (reason is not None) or (reason is not None and not reason.strip()):
        print(_REASON_REQUIRED_WITH_HOLD if hold else _REASON_REQUIRES_HOLD)
        raise SystemExit(1)

    body: _TodoUpdateBody = {
        "slug": slug,
        "cwd": str(resolve_invocation_cwd()),
        "client_request_id": str(uuid.uuid4()),
    }
    if new_slug is not None:
        body["new_slug"] = new_slug
    if after_present:
        body["after"] = after
    if schedule is not None:
        body["schedule"] = schedule
    if kind is not None:
        body["kind"] = kind
    if force:
        body["force"] = True
    if hold:
        body["hold"] = True
        body["reason"] = reason.strip()
    if release:
        body["release"] = True
    if unclaim:
        body["unclaim"] = True

    receipt: object = tool_api_call("POST", "/todos/update", json_body=body)
    if not isinstance(receipt, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        print_json(receipt)
        raise SystemExit(1)

    if "operation_id" not in receipt:
        print_json(receipt)
        return

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
    """Refuse retired or unknown artifact names for writes."""
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

    async def read_artifacts(todos_db: TodosDb) -> list[ArtifactWritersRow]:
        return await todos_db.list_artifacts_with_writers(slug, include_removed=True)

    artifacts = run_todo_read(read_artifacts)
    if not artifacts:
        print(f"No artifacts for {slug}")
    else:
        for entry in artifacts:
            print(f"  {entry['name']}")
            writers = entry.get("writers") or []
            if writers:
                print(f"    writers: {', '.join(writers)}")


def _handle_artifacts_read(args: list[str]) -> None:
    """Handle telec todo artifacts read <slug> <name>."""
    if len(args) < 2:
        print("Usage: telec todo artifacts read <slug> <name>")
        raise SystemExit(1)

    slug, name = args[0], args[1]
    _validate_artifact_name(name)

    async def read_artifact(todos_db: TodosDb) -> str:
        return await todos_db.read_artifact(slug, name, include_removed=True)

    print(run_todo_read(read_artifact))


def _handle_artifacts_diff(args: list[str]) -> None:
    """Handle telec todo artifacts diff <slug> <name> <old-digest> <new-digest>."""
    from teleclaude.core.todos_db import malformed_digest_detail  # noqa: PLC0415 - deferred command-local dependency.

    if len(args) < 4:
        print("Usage: telec todo artifacts diff <slug> <name> <old-digest> <new-digest>")
        raise SystemExit(1)

    slug, name, old_digest, new_digest = args[0], args[1], args[2], args[3]
    _validate_artifact_name(name)
    malformed_detail = malformed_digest_detail(old_digest, new_digest)
    if malformed_detail is not None:
        print(f"Error: {malformed_detail}", file=sys.stderr)
        raise SystemExit(1)

    async def read_diff(todos_db: TodosDb) -> str:
        return await todos_db.artifacts_diff(slug, name, old_digest, new_digest, include_removed=True)

    try:
        print(run_todo_read(read_diff))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _handle_artifacts_remove(args: list[str]) -> None:
    """Handle telec todo artifacts remove <slug> <name>."""
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - deferred command-local dependency.

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
        print(result, file=sys.stderr)
        raise SystemExit(1)

    if result.get("removed") is True:
        versions_deleted = result.get("versions_deleted", 0)
        print(f"Removed {name_val} for {slug_val}; deleted {versions_deleted} version rows.")
    else:
        print(f"No {name_val} artifact for {slug_val}; nothing needed to be removed.")


def _handle_artifacts_write(args: list[str]) -> None:
    """Handle telec todo artifacts write <slug> <name> <content>."""
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - deferred command-local dependency.
    from teleclaude.core.next_machine.git_ops import (  # noqa: PLC0415 - only artifact writes record the codebase head.
        get_head_commit,
    )

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
        },
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Wrote {name_val} for {slug_val}")
    else:
        print(result, file=sys.stderr)
        raise SystemExit(1)


# ── Reactivate handler ─────────────────────────────────────────────────────
# _handle_todo_show is imported from _todo_show.py (combines --include-removed
# and --include-artifact-content per the enrich-todo-show-payload merge).
# _handle_todo_stamp is imported from _todo_stamp.py to respect module size.


def _handle_todo_reactivate(args: list[str]) -> None:
    """Handle slug or durable-id reactivation of a soft-removed todo."""
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - deferred command-local dependency.

    parsed = parse_command_args(TODO_REACTIVATE, args)
    positionals = parsed.positionals
    row_id = parsed.value(F.FLAG_TODO_REACTIVATE_ID)
    if row_id is not None and not positionals:
        target_path = f"/todos/by-id/{row_id}/reactivate"
    elif len(positionals) == 1 and row_id is None:
        target_path = f"/todos/{positionals[0]}/reactivate"
    else:
        print("Usage: telec todo reactivate <slug> | --id <row-id>")
        raise SystemExit(1)

    result = tool_api_request("POST", target_path, json_body={"cwd": str(resolve_invocation_cwd())})

    if isinstance(result, dict) and result.get("slug"):
        print(f"Restored todo: {result['slug']}")
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(result)


_TODO_SUBCOMMAND_HANDLERS: dict[_TodoSubcommand, Callable[[list[str]], None]] = {
    _TodoSubcommand.ARTIFACTS: _handle_todo_artifacts,
    _TodoSubcommand.CREATE: _handle_todo_create,
    _TodoSubcommand.DELIVER: _handle_todo_deliver,
    _TodoSubcommand.DESIGN: _handle_todo_design,
    _TodoSubcommand.FREEZE: _handle_todo_freeze,
    _TodoSubcommand.INTEGRATE: _handle_todo_integrate,
    _TodoSubcommand.LIST: _handle_todo_list,
    _TodoSubcommand.PREPARE: _handle_todo_prepare,
    _TodoSubcommand.REACTIVATE: _handle_todo_reactivate,
    _TodoSubcommand.REMOVE: _handle_todo_remove,
    _TodoSubcommand.SHOW: _handle_todo_show,
    _TodoSubcommand.STAMP: _handle_todo_stamp,
    _TodoSubcommand.UNFREEZE: _handle_todo_unfreeze,
    _TodoSubcommand.UPDATE: _handle_todo_update,
    _TodoSubcommand.WORK: _handle_todo_work,
}
