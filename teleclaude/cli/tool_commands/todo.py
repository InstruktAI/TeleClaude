"""Todo workflow and operations subcommand handlers for telec todo/operations.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).
"""
# pylint: disable=import-outside-toplevel,raise-missing-from

from __future__ import annotations

import os
import sys
import uuid

from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.cli.tool_commands._receipt import poll_operation

__all__ = [
    "handle_operations",
    "handle_operations_get",
    "handle_todo_create",
    "handle_todo_integrate",
    "handle_todo_prepare",
    "handle_todo_set_deps",
    "handle_todo_work",
]


def handle_todo_create(args: list[str]) -> None:
    """Run the creative lifecycle state machine.

    Usage: telec todo co-create [<slug>]

    Checks creative state for the given slug and returns instructions for
    the next action: design discovery, art generation, visual drafting,
    or human gate signals.

    When called without a slug, selects the next work item that needs
    creative work from the roadmap.

    Options:
      <slug>    Work item slug (optional; auto-selects if omitted)

    Examples:
      telec todo co-create
      telec todo co-create my-feature
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_create.__doc__ or "")
        return

    cwd = os.getcwd()
    body: dict[str, object] = {"cwd": cwd}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

    data = tool_api_call("POST", "/todos/create", json_body=body)
    print_json(data)


def handle_todo_prepare(args: list[str]) -> None:
    """Run the Phase A (prepare) state machine.

    Usage: telec todo prepare [<slug>] [--invalidate-check [--changed-paths PATHS]]

    Checks preparation state for the given slug and returns instructions for
    the next action: draft artifacts (if not started), gate review (if draft
    complete), or signal already prepared (if gate passed).

    When called without a slug, selects the next unprepared work item from the
    roadmap. Requires orchestrator clearance (not available to workers).

    Options:
      <slug>                Work item slug (optional; auto-selects if omitted)
      --invalidate-check    Scan all active todos and invalidate stale preparations
      --changed-paths PATHS Comma-separated file paths for invalidation check

    Examples:
      telec todo prepare
      telec todo prepare my-feature
      telec todo prepare --invalidate-check --changed-paths src/foo.py,src/bar.py
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_prepare.__doc__ or "")
        return

    cwd = os.getcwd()

    # Handle --invalidate-check as a pure local mechanical operation (no API call)
    if "--invalidate-check" in args:
        from teleclaude.core.next_machine.core import invalidate_stale_preparations

        changed_paths: list[str] = []
        for idx, arg in enumerate(args):
            if arg == "--changed-paths" and idx + 1 < len(args):
                changed_paths = [p.strip() for p in args[idx + 1].split(",") if p.strip()]
        result = invalidate_stale_preparations(cwd, changed_paths)
        print_json(result)
        return

    body: dict[str, object] = {"cwd": cwd}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

    data = tool_api_call("POST", "/todos/prepare", json_body=body)
    print_json(data)


def handle_todo_work(args: list[str]) -> None:
    """Run the Phase B (work) state machine.

    Usage: telec todo work [<slug>]

    Executes the build/review/fix cycle on prepared work items. Dispatches
    worker agents for build, review, or fix-review phases as determined by the
    current state of the slug.

    Requires orchestrator clearance — workers cannot invoke this on themselves.
    Uses the current working directory as the project root.

    Options:
      <slug>       Work item slug (optional; auto-selects next ready item)

    Examples:
      telec todo work
      telec todo work my-feature
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_work.__doc__ or "")
        return

    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "cwd": os.getcwd(),
        "client_request_id": str(uuid.uuid4()),
    }

    i = 0
    while i < len(args):
        if args[i] == "--cwd":
            # Deprecated: todo work now always uses the shell cwd.
            # Keep parsing for backwards-compatible invocations.
            i += 2 if i + 1 < len(args) else 1
        elif not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

    receipt = tool_api_call("POST", "/todos/work", json_body=body)
    if not isinstance(receipt, dict):
        print_json(receipt)
        return

    status = poll_operation(receipt, estimated_timeout_ms=600_000)
    print_json(status)


def handle_todo_integrate(args: list[str]) -> None:
    """Run the integration state machine.

    Usage: telec todo integrate [<slug>]

    Executes the next deterministic integration step: acquires the integration
    lease, pops the next candidate from the queue, merges, pushes, and cleans
    up. Returns structured instructions at decision points where agent
    intelligence is required (squash commit, conflict resolution, push recovery).

    Requires integrator clearance. The queue is FIFO; if a slug is provided,
    it must match the next item or an error is returned.

    Options:
      <slug>       Candidate slug (optional; must match next in FIFO queue)

    Examples:
      telec todo integrate
      telec todo integrate my-feature
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_integrate.__doc__ or "")
        return

    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "cwd": os.getcwd(),
        "client_request_id": str(uuid.uuid4()),
    }

    i = 0
    while i < len(args):
        if not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

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

    Usage: telec operations get <operation_id>

    Examples:
      telec operations get 4ac5e6bf-53da-4862-95d3-bd75ed25b49f
    """
    if "--help" in args or "-h" in args:
        print(handle_operations_get.__doc__ or "")
        return

    operation_id = next((arg for arg in args if not arg.startswith("-")), None)
    if not operation_id:
        print("Error: operation_id required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("GET", f"/operations/{operation_id}")
    print_json(data)


def handle_todo_set_deps(args: list[str]) -> None:
    """Set dependencies for a work item in the roadmap.

    Usage: telec todo set-deps <slug> --after <dep1> [<dep2> ...]
                               OR
           telec todo set-deps <slug>   (clears all dependencies)

    Replaces all existing dependencies for the slug with the given list.
    Pass no --after flags to clear all dependencies. Validates all slugs
    against roadmap.yaml and detects circular dependencies.

    Options:
      <slug>           Work item slug
      --after <slug>   Dependency slug (can be repeated for multiple deps)

    Examples:
      telec todo set-deps my-feature --after auth-setup
      telec todo set-deps my-feature --after dep1 --after dep2
      telec todo set-deps my-feature   (clears deps)
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_set_deps.__doc__ or "")
        return

    slug: str | None = None
    after: list[str] = []
    cwd: str = os.getcwd()

    i = 0
    while i < len(args):
        if args[i] == "--after" and i + 1 < len(args):
            after.append(args[i + 1])
            i += 2
        elif not args[i].startswith("-"):
            slug = args[i]
            i += 1
        else:
            i += 1

    if not slug:
        print("Error: slug is required", file=sys.stderr)
        raise SystemExit(1)

    body: dict[str, object] = {"slug": slug, "after": after, "cwd": cwd}  # guard: loose-dict - JSON request body
    data = tool_api_call("POST", "/todos/set-deps", json_body=body)
    print_json(data)
