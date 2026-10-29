"""Handler for ``telec todo show``."""

from __future__ import annotations

import json as _json
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import addressed_computer, project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._todo_read import run_todo_read
from teleclaude.cli.telec.surface import TODO_SHOW
from teleclaude.cli.tool_client import ToolAPIError, tool_api_call, tool_api_request
from teleclaude.constants import SLUG_NOT_FOUND_DETAIL
from teleclaude.core.todos_db._show import (
    ClaimBlock,
    ShowPayload,
    TodoShowPayload,
    assemble_show_payload,
    payload_is_active_todo,
)
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.todos import ClaimStatus

__all__ = ["_handle_todo_show"]

logger = get_logger(__name__)

_USAGE = "Usage: telec todo show <slug> [--include-removed] [--include-artifact-content]"
# Longer than the daemon's read deadline (``CLAIM_READ_DEADLINE_S``), shorter than the client's default wait.
_CLAIM_READ_TIMEOUT_S = 25.0


def _undetermined_claim(slug: str, reason: str) -> ClaimBlock:
    """The block for a claim this command could not read; the daemon cannot record that it was not reached."""
    logger.warning("todo claim undetermined", slug=slug, reason=reason)
    return ClaimBlock(status=ClaimStatus.UNDETERMINED, reason=reason)


def _read_claim(slug: str) -> ClaimBlock:
    """Ask the daemon who holds the todo's claim; whatever keeps it from answering is ``undetermined``."""
    try:
        answer = tool_api_request(
            "GET", f"/todos/claim/{slug}", params={"cwd": project_reference()}, timeout=_CLAIM_READ_TIMEOUT_S
        )
    except ToolAPIError as error:
        return _undetermined_claim(slug, f"daemon not reachable: {error}")
    if not isinstance(answer, dict) or answer.get("status") not in tuple(ClaimStatus):
        return _undetermined_claim(slug, "daemon not reachable: unreadable answer")
    return cast(ClaimBlock, answer)


def _handle_todo_show(args: list[str]) -> None:
    """Display the diagnostic todo state payload as JSON."""
    parsed = parse_command_args(TODO_SHOW, args)
    positionals = parsed.positionals
    if len(positionals) != 1:
        print(_USAGE)
        raise SystemExit(1)
    slug = positionals[0]
    include_artifact_content = parsed.has(F.FLAG_TODO_SHOW_INCLUDE_ARTIFACT_CONTENT)
    include_removed = parsed.has(F.FLAG_TODO_SHOW_INCLUDE_REMOVED)

    async def read_show(todos_db: WorkflowStore) -> ShowPayload | None:
        return await assemble_show_payload(
            todos_db,
            slug,
            include_removed=include_removed,
            include_artifact_content=include_artifact_content,
        )

    if addressed_computer() is not None:
        remote = tool_api_call(
            "GET",
            f"/todos/show/{slug}",
            params={
                "cwd": project_reference(),
                "include_removed": include_removed,
                "include_artifact_content": include_artifact_content,
            },
        )
        print(_json.dumps(remote, indent=2))
        return

    result = run_todo_read(read_show)
    if result is not None:
        if payload_is_active_todo(result):
            cast(TodoShowPayload, result)["claim"] = _read_claim(slug)
        print(_json.dumps(result, indent=2))
    else:
        print(f"Error: {SLUG_NOT_FOUND_DETAIL.format(slug=slug)}")
        raise SystemExit(1)
