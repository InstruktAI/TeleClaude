"""Todo workflow and operations subcommand handlers for telec todo/operations.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).
"""

from __future__ import annotations

import json
import sys
import uuid

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import ParsedArgs, parse_command_args
from teleclaude.cli.telec.surface import OPERATIONS_GET, TODO_DESIGN, TODO_INTEGRATE, TODO_PREPARE, TODO_WORK
from teleclaude.cli.tool_client import ToolQueryParams, print_json, tool_api_call
from teleclaude.cli.tool_commands._receipt import poll_operation
from teleclaude.project_root import resolve_invocation_cwd

__all__ = [
    "handle_operations",
    "handle_operations_get",
    "handle_todo_create",
    "handle_todo_design",
    "handle_todo_integrate",
    "handle_todo_prepare",
    "handle_todo_work",
]


def _parse_single_slug(parsed: ParsedArgs) -> str | None:
    """Extract at most one positional slug, rejecting a second one loudly."""
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    return positionals[0] if positionals else None


def handle_todo_design(args: list[str]) -> None:
    """Run the creative lifecycle state machine.

    Usage: telec todo design [<slug>]

    Checks creative state for the given slug and returns instructions for
    the next action: design discovery, art generation, visual drafting,
    or human gate signals.

    When called without a slug, selects the next work item that needs
    creative work from the todo list.

    Options:
      <slug>    Work item slug (optional; auto-selects if omitted)

    Examples:
      telec todo design
      telec todo design my-feature
    """
    parsed = parse_command_args(TODO_DESIGN, args)
    slug = _parse_single_slug(parsed)
    body: dict[str, object] = {"cwd": str(resolve_invocation_cwd())}  # guard: loose-dict - JSON request body
    if slug is not None:
        body["slug"] = slug

    data = tool_api_call("POST", "/todos/create", json_body=body)
    print_json(data)


def handle_todo_create(args: list[str]) -> None:
    """Backward-compatible alias for the creative lifecycle state machine."""
    handle_todo_design(args)


def handle_todo_prepare(args: list[str]) -> None:
    """Run the Phase A (prepare) state machine.

    Usage: telec todo prepare <slug>

    Checks preparation state for the given slug and returns instructions for
    the next action: draft artifacts (if not started), gate review (if draft
    complete), or signal already prepared (if gate passed).

    A slug is required; invoking prepare without one is rejected. Requires
    orchestrator clearance (not available to workers).

    Options:
      <slug>       Work item slug (required)

    Examples:
      telec todo prepare my-feature
    """
    parsed = parse_command_args(TODO_PREPARE, args)
    slug = _parse_single_slug(parsed)
    body: dict[str, object] = {"cwd": str(resolve_invocation_cwd())}  # guard: loose-dict - JSON request body
    if slug is not None:
        body["slug"] = slug

    receipt = tool_api_call("POST", "/todos/prepare", json_body=body)
    if not isinstance(receipt, dict):
        print_json(receipt)
        return

    status = poll_operation(receipt, estimated_timeout_ms=300_000)
    result = status.get("result")
    if isinstance(result, str):
        try:
            status["result"] = json.loads(result)
        except json.JSONDecodeError:
            pass
    print_json(status)


def handle_todo_work(args: list[str]) -> None:
    """Run the Phase B (work) state machine.

    Usage: telec todo work [<slug>]

    Executes the build/review/fix cycle for the provided work item slug.
    Dispatches worker agents for build, review, or fix-review phases as
    determined by the current state of the slug. Without a slug, the command
    emits a terminal self-end script; daemon-runner pickup owns selecting
    future work.

    Requires orchestrator clearance — workers cannot invoke this on themselves.
    Uses the current working directory as the project root.

    Options:
      <slug>       Work item slug for the current orchestrator session

    Examples:
      telec todo work my-feature
    """
    parsed = parse_command_args(TODO_WORK, args)
    slug = _parse_single_slug(parsed)
    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "cwd": str(resolve_invocation_cwd()),
        "client_request_id": str(uuid.uuid4()),
    }
    if slug is not None:
        body["slug"] = slug

    receipt = tool_api_call("POST", "/todos/work", json_body=body)
    if not isinstance(receipt, dict):
        print_json(receipt)
        return

    status = poll_operation(receipt, estimated_timeout_ms=600_000)
    print_json(status)


def handle_todo_integrate(args: list[str]) -> None:
    """Run the integration state machine.

    Usage: telec todo integrate [<slug>] [--abandon]

    Executes the next deterministic integration step: acquires the integration
    lease, pops the next candidate from the queue, merges, pushes, and cleans
    up. Returns structured instructions at decision points where agent
    intelligence is required (squash commit, conflict resolution, push recovery).

    Requires integrator clearance. The queue is FIFO; if a slug is provided,
    it must match the next item or an error is returned.

    Options:
      <slug>       Candidate slug (optional; must match next in FIFO queue)
      --abandon    Park the current CONTENT_GATE_BLOCKED candidate as an
                   ungroundable content-gate concern. The state machine resets
                   the integration worktree to the frozen pre-merge SHA and
                   parks; refused when the checkpoint is not at that phase.

    Examples:
      telec todo integrate
      telec todo integrate my-feature
      telec todo integrate --abandon
    """
    parsed = parse_command_args(TODO_INTEGRATE, args)
    slug = _parse_single_slug(parsed)
    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "cwd": str(resolve_invocation_cwd()),
        "client_request_id": str(uuid.uuid4()),
    }
    if slug is not None:
        body["slug"] = slug
    if parsed.has(F.FLAG_TODO_INTEGRATE_ABANDON):
        body["abandon"] = True

    receipt = tool_api_call("POST", "/todos/integrate", json_body=body)
    if not isinstance(receipt, dict):
        print_json(receipt)
        return

    status = poll_operation(receipt, estimated_timeout_ms=300_000)
    print_json(status)


def handle_operations(args: list[str]) -> None:
    """Handle telec operations <subcommand> [args].

    Subcommands:
      get         Fetch durable operation status by operation_id
    """
    if not args or args[0] in ("-h", "--help"):
        _operations_help()
        return

    sub = args[0]
    rest = args[1:]
    if sub == "get":
        handle_operations_get(rest)
        return

    print(f"Unknown operations subcommand: {sub}", file=sys.stderr)
    print("Run 'telec operations --help' for usage.", file=sys.stderr)
    raise SystemExit(1)


def _operations_help() -> None:
    print(
        """Usage: telec operations <subcommand> [args]

Subcommands:
  get          Fetch durable operation status by operation_id

Run 'telec operations <subcommand> --help' for subcommand-specific help."""
    )


def handle_operations_get(args: list[str]) -> None:
    """Fetch durable operation status by operation_id.

    Usage: telec operations get <operation_id> [-c/--computer <computer>]

    Options:
      -c, --computer    Read the operation from a named remote computer,
                        forwarded by the local daemon to the owning computer.

    Examples:
      telec operations get 4ac5e6bf-53da-4862-95d3-bd75ed25b49f
      telec operations get 4ac5e6bf-53da-4862-95d3-bd75ed25b49f --computer mac-studio
    """
    if "--help" in args or "-h" in args:
        print(handle_operations_get.__doc__ or "")
        return

    parsed = parse_command_args(OPERATIONS_GET, args)
    operation_id = _parse_single_slug(parsed)
    if not operation_id:
        print("Error: operation_id required", file=sys.stderr)
        raise SystemExit(1)

    computer = parsed.value(F.FLAG_COMPUTER)
    params: ToolQueryParams | None = {"computer": computer} if computer else None
    data = tool_api_call("GET", f"/operations/{operation_id}", params=params)
    print_json(data)
