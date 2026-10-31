"""Run synchronous CLI todo reads against the local workflow store."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NoReturn

from teleclaude.cli.telec.handlers._todo_roots import _resolve_project_root_or_exit
from teleclaude.core.workflow_store.github import GitHubIdentityRefusal, GitHubIdentityRefused
from teleclaude.core.workflow_store.github_io_transport import GitHubIORefused
from teleclaude.core.workflow_store.github_store import GitHubStoreSelectionRefused
from teleclaude.core.workflow_store.store import WorkflowStore, close_workflow_stores, get_workflow_store
from teleclaude.paths import PROJECTS_MANIFEST_PATH, ConfigFileName

_GITHUB_UNREACHABLE = frozenset(
    {
        GitHubIdentityRefusal.CREDENTIAL_REFUSED,
        GitHubIdentityRefusal.RATE_LIMITED,
        GitHubIdentityRefusal.PROVIDER_UNAVAILABLE,
    }
)
_GITHUB_UNREACHABLE_DETAIL = (
    "the GitHub workflow store could not be reached ({reason}). Retry, or check `telec app status`."
)


def _github_identity_refusal_detail(reason: GitHubIdentityRefusal, project_root: Path) -> str:
    """Name a GitHub workflow-store refusal in plain words and the act that resolves it."""
    if reason is GitHubIdentityRefusal.UNREGISTERED_PROJECT:
        return (
            f"{project_root} is not a registered project in {PROJECTS_MANIFEST_PATH}. "
            "Register it by running `telec config project adopt` from that folder."
        )
    if reason in _GITHUB_UNREACHABLE:
        return _GITHUB_UNREACHABLE_DETAIL.format(reason=reason)
    return f"the GitHub workflow store refused this project ({reason})."


def run_todo_read[T](operation: Callable[[WorkflowStore], Awaitable[T]]) -> T:
    """Run one workflow-store read for the invocation project after CLI clearance.

    A GitHub workflow-store refusal exits with a clean CLI error naming its cause and door.
    """
    project_root = _resolve_project_root_or_exit()

    async def run() -> T:
        todos_db = await get_workflow_store(project_root)
        try:
            return await operation(todos_db)
        finally:
            await close_workflow_stores()

    try:
        return asyncio.run(run())
    except GitHubIdentityRefused as refused:
        _exit_refused(_github_identity_refusal_detail(refused.reason, project_root), refused)
    except GitHubStoreSelectionRefused as refused:
        declaration = project_root / ConfigFileName.OVERLAY
        _exit_refused(f"{refused}. Fix `todos.app` in {declaration}.", refused)
    except GitHubIORefused as refused:
        _exit_refused(_GITHUB_UNREACHABLE_DETAIL.format(reason=refused.reason), refused)


def _exit_refused(detail: str, refused: Exception) -> NoReturn:
    print(f"Error: {detail}", file=sys.stderr)
    raise SystemExit(1) from refused
