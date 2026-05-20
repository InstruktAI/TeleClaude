"""Handlers for telec todo commands."""

from __future__ import annotations

import asyncio
import json as _json
import sys
import uuid
from typing import Literal

from teleclaude.api_models import TodoDumpRequest
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
from teleclaude.core.next_machine.git_ops import extract_referenced_paths, get_head_commit
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, LifecycleStage
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_io import mark_phase_state, reconcile_phase_state
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.core.todos_db import close_todos_db_instances
from teleclaude.events.producer import ensure_event_producer
from teleclaude.git import GitCommandError
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.session_identity import get_session_id

__all__ = [
    "_handle_todo",
    "_handle_todo_artifacts",
    "_handle_todo_create",
    "_handle_todo_design",
    "_handle_todo_dump",
    "_handle_todo_mark_phase",
    "_handle_todo_reconcile",
    "_handle_todo_remove",
    "_handle_todo_rename",
    "_handle_todo_show",
    "_handle_todo_split",
    "_handle_todo_stamp",
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
    if subcommand == "create":
        _handle_todo_create(args[1:])
    elif subcommand in ("design", "co-create"):
        _handle_todo_design(args[1:])
    elif subcommand == "remove":
        _handle_todo_remove(args[1:])
    elif subcommand == "rename":
        _handle_todo_rename(args[1:])
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
    elif subcommand == "mark-phase":
        _handle_todo_mark_phase(args[1:])
    elif subcommand == "reconcile":
        _handle_todo_reconcile(args[1:])
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


def _handle_todo_create(args: list[str]) -> None:
    """Handle telec todo create <slug> <content> [--after <deps>] [--silent] [--prepped]."""
    slug: str | None = None
    content: str | None = None
    after: list[str] | None = None
    silent = False
    prepped = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg == "--silent":
            silent = True
            i += 1
        elif arg == "--prepped":
            prepped = True
            i += 1
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

    dump_kind: Literal["bug", "draft", "prepped"] | None = "prepped" if prepped else None

    request = TodoDumpRequest(
        slug=slug,
        content=content,
        after=after,
        kind=dump_kind,
        cwd=str(resolve_invocation_cwd()),
        silent=silent,
    )
    result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body=request.model_dump(mode="json"),
        timeout=10.0,
    )

    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Created todo: {slug}" + (" (prepped, ready for build)" if prepped else ""))
    else:
        print(f"Error: unexpected response: {result}")
        raise SystemExit(1)


def _handle_todo_design(args: list[str]) -> None:
    """Handle telec todo design [<slug>]."""
    handle_todo_design(args)


def _handle_todo_dump(args: list[str]) -> None:
    """DEPRECATED — alias for telec todo create. Use telec todo create instead."""
    print("Warning: 'telec todo dump' is deprecated. Use 'telec todo create' instead.", file=sys.stderr)
    translated = ["--silent" if arg == "--draft" else arg for arg in args]
    _handle_todo_create(translated)


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


# ---------------------------------------------------------------------------
# Artifact and stamp handlers (todos.db backed)
# ---------------------------------------------------------------------------


def _validate_artifact_name(name: str) -> None:
    """Reject unknown artifact names before dispatching to the API."""
    if name not in ARTIFACT_NAMES:
        print(f"Unknown artifact name: {name!r}")
        print(f"Valid names: {', '.join(sorted(ARTIFACT_NAMES))}")
        raise SystemExit(1)


def _validate_artifact_name_write(name: str) -> None:
    """Reject unknown or retired artifact names on the write path.

    Retired names (e.g. ``test-specs``, ``spec-review-findings``) are accepted
    by ``_validate_artifact_name`` for read/remove of pre-cutover todos but must
    not be writeable.
    """
    if name not in ARTIFACT_NAMES_WRITABLE:
        if name in ARTIFACT_NAMES_RETIRED:
            print(
                f"Refusing to write retired artifact {name!r}: this artifact kind is no "
                f"longer produced. Reads and removes of pre-cutover todos remain supported."
            )
        else:
            print(f"Unknown artifact name: {name!r}")
            print(f"Writable names: {', '.join(sorted(ARTIFACT_NAMES_WRITABLE))}")
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
    slug: str | None = None
    name: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec todo artifacts remove <slug> <name>")
            raise SystemExit(1)
        if slug is None:
            slug = arg
        elif name is None:
            name = arg
        else:
            print("Too many positional arguments.")
            print("Usage: telec todo artifacts remove <slug> <name>")
            raise SystemExit(1)
        i += 1

    if not slug or not name:
        print("Usage: telec todo artifacts remove <slug> <name>")
        raise SystemExit(1)

    _validate_artifact_name(name)
    if name == ARTIFACT_INPUT:
        print("input artifact cannot be removed")
        raise SystemExit(1)

    result = tool_api_request(
        "DELETE",
        f"/todos/artifacts/{slug}/{name}",
        params={"cwd": str(resolve_invocation_cwd())},
    )
    if not isinstance(result, dict) or result.get("status") != "ok":
        print(result)
        raise SystemExit(1)

    if result.get("removed") is True:
        versions_deleted = result.get("versions_deleted", 0)
        print(f"Removed {name} for {slug}; deleted {versions_deleted} version rows.")
    else:
        print(f"No {name} artifact for {slug}; nothing needed to be removed.")


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

    _validate_artifact_name_write(name)
    cwd = str(resolve_invocation_cwd())
    result = tool_api_request(
        "POST",
        f"/todos/artifacts/{slug}/{name}",
        json_body={
            "content": content,
            "cwd": cwd,
            "codebase_sha_at_write": get_head_commit(cwd),
            "referenced_paths": extract_referenced_paths(content, cwd),
        },
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        print(f"Wrote {name} for {slug}")
    else:
        print(result)


def _handle_todo_stamp(args: list[str]) -> None:
    """Handle telec todo stamp.

    Supported flag combinations:
      --verdict <approve|changes_requested|needs_work|needs_decision> --phase <phase>
      --prd-approved
      --architecture-skipped <reason>
      --drift-reviewed <artifact> <verdict> <reason>
      --deferrals-processed
      --design-spec-confirmed
      --art-approved
      --visuals-approved
      --build-complete
      --finalize-ready
    """
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
