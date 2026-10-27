"""Handlers for telec todo commands."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPMethod
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import addressed_computer, project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    TODO_BOARD_REPAIR,
    TODO_COMMAND,
    TODO_CREATE,
    TODO_DELIVER,
    TODO_REACTIVATE,
    TODO_REMOVE,
)
from teleclaude.constants import (
    ARTIFACT_INPUT,
    ARTIFACT_NAMES,
    ARTIFACT_NAMES_PLATFORM_WRITTEN,
    ARTIFACT_NAMES_RETIRED,
    ARTIFACT_NAMES_WRITABLE,
    ARTIFACT_PLATFORM_WRITTEN_REFUSAL,
    SLUG_NOT_FOUND_DETAIL,
    SLUG_NOT_IN_ICEBOX_DETAIL,
)
from teleclaude.slug import validate_slug

if TYPE_CHECKING:
    from teleclaude.core.todos_db._rows import ArtifactWritersRow
    from teleclaude.core.workflow_store.store import WorkflowStore
    from teleclaude.services.work.slug_actions import SlugActionResult


class _TodoUpdateBody(TypedDict):
    slug: str
    cwd: str
    client_request_id: str
    new_slug: NotRequired[str]
    group: NotRequired[str]
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
_TODO_CREATE_KIND_REQUIRED_TEMPLATE = "Error: --kind is required. Valid values: {valid_kinds}"
_TODO_CREATE_KIND_INVALID_TEMPLATE = "Error: invalid --kind '{kind}'. Valid values: {valid_kinds}"
_TODO_FILING_PATH = "/todos/dump"
_JSON_DUMP_MODE = "json"
_TODO_STORE_SWITCH_PATH = "/todos/switch-to-github"
_TODO_SWITCH_CWD_FIELD = "cwd"
_TODO_SWITCH_REQUEST_FIELD = "client_request_id"
_TODO_SWITCH_ARGUMENT_ERROR = "This command takes no arguments."
_TODO_BOARD_REPAIR_PATH = "/todos/board/repair"
_TODO_BOARD_REPAIR = "repair"
_TODO_BOARD_UNKNOWN_TEMPLATE = "Unknown board subcommand: {subcommand}"


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
    BOARD = "board"
    CREATE = "create"
    DELIVER = "deliver"
    DESIGN = "design"
    FREEZE = "freeze"
    INTEGRATE = "integrate"
    LIST = "list"
    PREPARE = "prepare"
    REACTIVATE = "reactivate"
    RETURN_TO_WORK = "return-to-work"
    REMOVE = "remove"
    SWITCH_TO_GITHUB = "switch-to-github"
    SHOW = "show"
    STAMP = "stamp"
    SYNC = "sync"
    SYNC_REPLICA = "sync-replica"
    UNFREEZE = "unfreeze"
    UPDATE = "update"
    WORK = "work"


__all__ = [
    "_handle_todo",
    "_handle_todo_artifacts",
    "_handle_todo_board",
    "_handle_todo_create",
    "_handle_todo_deliver",
    "_handle_todo_design",
    "_handle_todo_freeze",
    "_handle_todo_list",
    "_handle_todo_remove",
    "_handle_todo_show",
    "_handle_todo_stamp",
    "_handle_todo_switch_to_github",
    "_handle_todo_sync",
    "_handle_todo_sync_replica",
    "_handle_todo_unfreeze",
    "_handle_todo_update",
]


def _handle_todo_sync(args: list[str]) -> None:
    """Handle the public todo-state transfer command."""
    from teleclaude.cli.telec.handlers.todo_sync import (  # noqa: PLC0415 - command boundary: transfer dependencies.
        handle_todo_sync,
    )

    handle_todo_sync(args)


def _handle_todo_sync_replica(args: list[str]) -> None:
    """Handle the hidden target-side transfer helper."""
    from teleclaude.cli.telec.handlers.todo_sync import (  # noqa: PLC0415 - command boundary: transfer dependencies.
        handle_todo_sync_replica,
    )

    handle_todo_sync_replica(args)


def _handle_todo_list(args: list[str]) -> None:
    """Handle telec todo list."""
    from teleclaude.cli.telec.handlers.todo_list import (  # noqa: PLC0415 - command boundary: list reads and renders.
        _handle_todo_list as handle_list,
    )

    handle_list(args)


def _handle_todo_show(args: list[str]) -> None:
    """Handle telec todo show."""
    from teleclaude.cli.telec.handlers._todo_show import (  # noqa: PLC0415 - command boundary: show reads local state.
        _handle_todo_show as handle_show,
    )

    handle_show(args)


def _handle_todo_stamp(args: list[str]) -> None:
    """Handle telec todo stamp."""
    from teleclaude.cli.telec.handlers._todo_stamp import (  # noqa: PLC0415 - command boundary: stamp uses the API client.
        _handle_todo_stamp as handle_stamp,
    )

    handle_stamp(args)


def _handle_todo_return_to_work(args: list[str]) -> None:
    """Handle the bounded code-conformance return operation."""
    from teleclaude.cli.telec.handlers._todo_return_to_work import (  # noqa: PLC0415 - command boundary: API mutation.
        _handle_todo_return_to_work as handle_return,
    )

    handle_return(args)


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


class _SlugAction(StrEnum):
    """Slug-addressed todo actions the daemon serves."""

    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    DELIVER = "deliver"


_CWD_FIELD = "cwd"
_COMMIT_FIELD = "commit"
_SLUG_ACTION_PATH = "/todos/{slug}/{action}"
_QUICK_ACTION_TIMEOUT_SECONDS = 30.0
# Delivery reconciles lifecycle markers through a hook-bearing git commit and then cleans up the
# worktree and branches, each git step under its own bound. A request cut short while the daemon
# completes the delivery would leave the outcome unknown, so the budget covers the whole chain.
_DELIVER_TIMEOUT_SECONDS = 300.0
_SLUG_ACTION_TIMEOUT_SECONDS: dict[_SlugAction, float] = {
    _SlugAction.FREEZE: _QUICK_ACTION_TIMEOUT_SECONDS,
    _SlugAction.UNFREEZE: _QUICK_ACTION_TIMEOUT_SECONDS,
    _SlugAction.DELIVER: _DELIVER_TIMEOUT_SECONDS,
}


def _perform_slug_action(action: _SlugAction, slug: str, commit: str | None = None) -> SlugActionResult:
    """Ask the daemon of the addressed computer, or of this one, to run one slug-addressed action."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.services.work.slug_actions import SlugActionResult  # noqa: PLC0415 - command boundary: result.

    body: dict[str, str] = {_CWD_FIELD: project_reference()}
    if commit is not None:
        body[_COMMIT_FIELD] = commit
    answer = tool_api_call(
        HTTPMethod.POST,
        _SLUG_ACTION_PATH.format(slug=slug, action=action.value),
        json_body=body,
        timeout=_SLUG_ACTION_TIMEOUT_SECONDS[action],
    )
    return SlugActionResult.from_dict(answer)


def _handle_todo_freeze(args: list[str]) -> None:
    """Handle telec todo freeze <slug>."""
    from teleclaude.services.work.slug_actions import SlugActionOutcome  # noqa: PLC0415 - command boundary: outcome.

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
    result = _perform_slug_action(_SlugAction.FREEZE, slug)
    if result.outcome is SlugActionOutcome.NOT_FOUND:
        print(SLUG_NOT_FOUND_DETAIL.format(slug=slug))
        raise SystemExit(1)
    print(f"Froze {slug} → icebox")
    for warning in result.warnings:
        print(warning)


def _handle_todo_unfreeze(args: list[str]) -> None:
    """Handle telec todo unfreeze <slug>."""
    from teleclaude.services.work.slug_actions import SlugActionOutcome  # noqa: PLC0415 - command boundary: outcome.

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
    result = _perform_slug_action(_SlugAction.UNFREEZE, slug)
    if result.outcome is SlugActionOutcome.NOT_FOUND:
        print(SLUG_NOT_IN_ICEBOX_DETAIL.format(slug=slug))
        raise SystemExit(1)
    print(f"Unfroze {slug} → todo list")
    for warning in result.warnings:
        print(warning)


def _handle_todo_deliver(args: list[str]) -> None:
    """Handle telec todo deliver <slug> [--commit SHA]."""
    from teleclaude.services.work.slug_actions import SlugActionOutcome  # noqa: PLC0415 - command boundary: outcome.

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
    result = _perform_slug_action(_SlugAction.DELIVER, slug, commit)
    if result.outcome is SlugActionOutcome.REFUSED:
        print(result.detail)
        raise SystemExit(1)
    if result.outcome is SlugActionOutcome.NOT_FOUND:
        print(SLUG_NOT_FOUND_DETAIL.format(slug=slug))
        raise SystemExit(1)
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
    from teleclaude.api_models import TodoDumpRequest  # noqa: PLC0415 - command boundary: create request model.
    from teleclaude.cli.telec.handlers._creation_gate import (  # noqa: PLC0415 - command boundary: creation gate.
        render_todo_creation_gate,
    )
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - command boundary: receipt rendering.
        render_receipt,
    )
    from teleclaude.types.todo_kind import (  # noqa: PLC0415 - command boundary: kind vocabulary.
        ALL_DUMP_KINDS,
        TODO_KIND_USAGE,
        TodoDumpKind,
    )

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

    if parsed.kind_value is None:
        print(_TODO_CREATE_KIND_REQUIRED_TEMPLATE.format(valid_kinds=_VALID_KINDS_STR))
        print(_usage("todo", "create"))
        raise SystemExit(1)
    if parsed.kind_value not in ALL_DUMP_KINDS:
        print(_TODO_CREATE_KIND_INVALID_TEMPLATE.format(kind=parsed.kind_value, valid_kinds=_VALID_KINDS_STR))
        print(_usage("todo", "create"))
        raise SystemExit(1)

    # The interrogation gate: a complete creation request without the
    # acknowledgment flag is the designed discovery moment (mirrors the bug
    # filing gate) - serving it is the successful outcome, so this exits 0
    # and creates nothing. The gate verifies the pre-creation decisions were
    # faced, never that the answers are true.
    if not parsed.approved:
        print(render_todo_creation_gate(_CREATION_ACK_FLAG), file=sys.stderr, end="")
        return

    dump_kind = cast(TodoDumpKind, parsed.kind_value)

    request = TodoDumpRequest(
        slug=slug,
        content=content,
        after=parsed.after,
        schedule=parsed.schedule,
        kind=dump_kind,
        cwd=parsed.project_root if parsed.project_root is not None else project_reference(),
        icebox=parsed.icebox,
        group=parsed.group,
        plan=parsed.plan,
        hold=parsed.hold,
        reason=parsed.reason.strip() if parsed.reason is not None else None,
        human_involved=parsed.human_involvement_reason is not None,
        human_involvement_reason=parsed.human_involvement_reason,
        client_request_id=str(uuid.uuid4()),
    )
    render_receipt(
        tool_api_request(HTTPMethod.POST, _TODO_FILING_PATH, json_body=request.model_dump(mode=_JSON_DUMP_MODE))
    )


def _handle_todo_design(args: list[str]) -> None:
    """Handle telec todo design [<slug>]."""
    from teleclaude.cli.tool_commands.todo import handle_todo_design  # noqa: PLC0415 - command boundary: handler.

    handle_todo_design(args)


def _handle_todo_integrate(args: list[str]) -> None:
    """Handle telec todo integrate <slug>."""
    from teleclaude.cli.tool_commands.todo import handle_todo_integrate  # noqa: PLC0415 - command boundary: handler.

    handle_todo_integrate(args)


def _handle_todo_prepare(args: list[str]) -> None:
    """Handle telec todo prepare <slug>."""
    from teleclaude.cli.tool_commands.todo import handle_todo_prepare  # noqa: PLC0415 - command boundary: handler.

    handle_todo_prepare(args)


def _handle_todo_work(args: list[str]) -> None:
    """Handle telec todo work [<slug>]."""
    from teleclaude.cli.tool_commands.todo import handle_todo_work  # noqa: PLC0415 - command boundary: handler.

    handle_todo_work(args)


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove — delete state, artifacts, and todo entry from todos.db.

    Also cleans up worktree and branch if they exist. Prints an operation receipt; the
    removal's outcome, including a refusal, is delivered to the calling session.
    """
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - command boundary: receipt rendering.
        render_receipt,
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
        "cwd": project_reference(),
        "client_request_id": str(uuid.uuid4()),
    }
    render_receipt(tool_api_call("POST", "/todos/remove", json_body=body))


def _handle_todo_switch_to_github(args: list[str]) -> None:
    """Submit the project store switch once and render its durable receipt."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - command boundary: receipt rendering.
        render_receipt,
    )

    if args:
        print(_TODO_SWITCH_ARGUMENT_ERROR)
        print(_usage(TODO_COMMAND, _TodoSubcommand.SWITCH_TO_GITHUB))
        raise SystemExit(1)
    body = {
        _TODO_SWITCH_CWD_FIELD: project_reference(),
        _TODO_SWITCH_REQUEST_FIELD: str(uuid.uuid4()),
    }
    render_receipt(tool_api_call(HTTPMethod.POST, _TODO_STORE_SWITCH_PATH, json_body=body))


def _handle_todo_board(args: list[str]) -> None:
    """Handle telec todo board repair: submit the board repair once and render its durable receipt."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - command boundary: receipt rendering.
        render_receipt,
    )

    if not args:
        print(_usage(TODO_COMMAND, _TodoSubcommand.BOARD))
        raise SystemExit(1)
    if args[0] != _TODO_BOARD_REPAIR:
        print(_TODO_BOARD_UNKNOWN_TEMPLATE.format(subcommand=args[0]))
        print(_usage(TODO_COMMAND, _TodoSubcommand.BOARD))
        raise SystemExit(1)
    parsed = parse_command_args(TODO_BOARD_REPAIR, args[1:])
    if parsed.positionals:
        print(_TODO_SWITCH_ARGUMENT_ERROR)
        print(_usage(TODO_COMMAND, _TodoSubcommand.BOARD))
        raise SystemExit(1)
    body = {
        _TODO_SWITCH_CWD_FIELD: project_reference(),
        _TODO_SWITCH_REQUEST_FIELD: str(uuid.uuid4()),
    }
    render_receipt(tool_api_call(HTTPMethod.POST, _TODO_BOARD_REPAIR_PATH, json_body=body))


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
    from teleclaude.cli.telec.handlers.todo_update_args import (  # noqa: PLC0415 - command boundary: update arguments.
        _parse_todo_update_args,
    )
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - command boundary: receipt rendering.
        render_receipt,
    )
    from teleclaude.types.todo_kind import (  # noqa: PLC0415 - command boundary: kind vocabulary.
        ALL_DUMP_KINDS,
        TODO_KIND_USAGE,
    )

    parsed = _parse_todo_update_args(args)
    slug = parsed["slug"]
    new_slug = parsed["new_slug"]
    group = parsed["group"]
    after_present = parsed["after_present"]
    kind = parsed["kind"]
    schedule = parsed["schedule"]
    force = parsed["force"]
    hold = parsed["hold"]
    reason = parsed["reason"]
    release = parsed["release"]
    unclaim = parsed["unclaim"]
    after = _normalize_after_values(parsed["raw_after"]) if after_present else []

    normalized_group = group.strip() if group is not None else None
    _validate_slugs(slug, new_slug, normalized_group or None, *after)
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
        "cwd": project_reference(),
        "client_request_id": str(uuid.uuid4()),
    }
    if new_slug is not None:
        body["new_slug"] = new_slug
    if group is not None:
        body["group"] = normalized_group or ""
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

    render_receipt(tool_api_call("POST", "/todos/update", json_body=body))


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
        elif name in ARTIFACT_NAMES_PLATFORM_WRITTEN:
            print(ARTIFACT_PLATFORM_WRITTEN_REFUSAL.format(name=name), file=sys.stderr)
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


def _remote_read(
    path: str, extra_params: dict[str, str] | None = None
) -> dict[str, object]:  # guard: loose-dict - JSON body
    """Read from the addressed computer's workflow store, naming the project this invocation acts on."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.

    answer = tool_api_call("GET", path, params={"cwd": project_reference(), **(extra_params or {})})
    if not isinstance(answer, dict):
        print(f"Error: unexpected response: {answer}", file=sys.stderr)
        raise SystemExit(1)
    return cast(dict[str, object], answer)  # guard: loose-dict - JSON body


def _handle_artifacts_list(args: list[str]) -> None:
    """Handle telec todo artifacts list <slug>."""
    from teleclaude.cli.telec.handlers._todo_read import (  # noqa: PLC0415 - command boundary: local workflow-store read.
        run_todo_read,
    )

    if not args or args[0].startswith("-"):
        print("Usage: telec todo artifacts list <slug>")
        raise SystemExit(1)

    slug = args[0]

    async def read_artifacts(todos_db: WorkflowStore) -> list[ArtifactWritersRow]:
        return await todos_db.list_artifacts_with_writers(slug, include_removed=True)

    if addressed_computer() is not None:
        remote = _remote_read(f"/todos/artifacts/{slug}")
        artifacts = cast("list[ArtifactWritersRow]", remote.get("artifacts") or [])
    else:
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
    from teleclaude.cli.telec.handlers._todo_read import (  # noqa: PLC0415 - command boundary: local workflow-store read.
        run_todo_read,
    )

    if len(args) < 2:
        print("Usage: telec todo artifacts read <slug> <name>")
        raise SystemExit(1)

    slug, name = args[0], args[1]
    _validate_artifact_name(name)

    async def read_artifact(todos_db: WorkflowStore) -> str:
        return await todos_db.read_artifact(slug, name, include_removed=True)

    if addressed_computer() is not None:
        print(_remote_read(f"/todos/artifacts/{slug}/{name}")["content"])
        return
    print(run_todo_read(read_artifact))


def _handle_artifacts_diff(args: list[str]) -> None:
    """Handle telec todo artifacts diff <slug> <name> <old-digest> <new-digest>."""
    from teleclaude.cli.telec.handlers._todo_read import (  # noqa: PLC0415 - command boundary: local workflow-store read.
        run_todo_read,
    )
    from teleclaude.core.todos_db._artifacts import (  # noqa: PLC0415 - command boundary: digest check.
        malformed_digest_detail,
    )

    if len(args) < 4:
        print("Usage: telec todo artifacts diff <slug> <name> <old-digest> <new-digest>")
        raise SystemExit(1)

    slug, name, old_digest, new_digest = args[0], args[1], args[2], args[3]
    _validate_artifact_name(name)
    malformed_detail = malformed_digest_detail(old_digest, new_digest)
    if malformed_detail is not None:
        print(f"Error: {malformed_detail}", file=sys.stderr)
        raise SystemExit(1)

    async def read_diff(todos_db: WorkflowStore) -> str:
        return await todos_db.artifacts_diff(slug, name, old_digest, new_digest, include_removed=True)

    if addressed_computer() is not None:
        remote = _remote_read(
            f"/todos/artifacts/{slug}/{name}/diff", {"old_digest": old_digest, "new_digest": new_digest}
        )
        print(remote["diff"])
        return
    try:
        print(run_todo_read(read_diff))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _handle_artifacts_remove(args: list[str]) -> None:
    """Handle telec todo artifacts remove <slug> <name>."""
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - command boundary: daemon API client.

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
    if name_val in ARTIFACT_NAMES_PLATFORM_WRITTEN:
        print(ARTIFACT_PLATFORM_WRITTEN_REFUSAL.format(name=name_val), file=sys.stderr)
        raise SystemExit(1)
    if name_val == ARTIFACT_INPUT:
        print("input artifact cannot be removed")
        raise SystemExit(1)

    result = tool_api_request(
        "DELETE",
        f"/todos/artifacts/{slug_val}/{name_val}",
        params={"cwd": project_reference()},
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
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - command boundary: daemon API client.
    from teleclaude.core.next_machine.git_ops import (  # noqa: PLC0415 - command boundary: codebase head at write.
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
    cwd = project_reference()
    result = tool_api_request(
        "POST",
        f"/todos/artifacts/{slug_val}/{name_val}",
        json_body={
            "content": content_val,
            "cwd": cwd,
            "codebase_sha_at_write": None if addressed_computer() is not None else get_head_commit(cwd),
        },
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Wrote {name_val} for {slug_val}")
    else:
        print(result, file=sys.stderr)
        raise SystemExit(1)


# ── Reactivate handler ─────────────────────────────────────────────────────


def _handle_todo_reactivate(args: list[str]) -> None:
    """Handle slug or durable-id reactivation of a soft-removed todo."""
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - command boundary: daemon API client.

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

    result = tool_api_request("POST", target_path, json_body={"cwd": project_reference()})

    if isinstance(result, dict) and result.get("slug"):
        print(f"Restored todo: {result['slug']}")
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(result)


_TODO_SUBCOMMAND_HANDLERS: dict[_TodoSubcommand, Callable[[list[str]], None]] = {
    _TodoSubcommand.ARTIFACTS: _handle_todo_artifacts,
    _TodoSubcommand.BOARD: _handle_todo_board,
    _TodoSubcommand.CREATE: _handle_todo_create,
    _TodoSubcommand.DELIVER: _handle_todo_deliver,
    _TodoSubcommand.DESIGN: _handle_todo_design,
    _TodoSubcommand.FREEZE: _handle_todo_freeze,
    _TodoSubcommand.INTEGRATE: _handle_todo_integrate,
    _TodoSubcommand.LIST: _handle_todo_list,
    _TodoSubcommand.PREPARE: _handle_todo_prepare,
    _TodoSubcommand.REACTIVATE: _handle_todo_reactivate,
    _TodoSubcommand.RETURN_TO_WORK: _handle_todo_return_to_work,
    _TodoSubcommand.REMOVE: _handle_todo_remove,
    _TodoSubcommand.SWITCH_TO_GITHUB: _handle_todo_switch_to_github,
    _TodoSubcommand.SHOW: _handle_todo_show,
    _TodoSubcommand.STAMP: _handle_todo_stamp,
    _TodoSubcommand.SYNC: _handle_todo_sync,
    _TodoSubcommand.SYNC_REPLICA: _handle_todo_sync_replica,
    _TodoSubcommand.UNFREEZE: _handle_todo_unfreeze,
    _TodoSubcommand.UPDATE: _handle_todo_update,
    _TodoSubcommand.WORK: _handle_todo_work,
}
