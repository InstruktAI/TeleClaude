"""Run synchronous CLI todo reads against the local workflow store."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from teleclaude.cli.telec.handlers._todo_roots import _resolve_project_root_or_exit
from teleclaude.core.workflow_store.github import GitHubIdentityRefusal, GitHubIdentityRefused
from teleclaude.core.workflow_store.store import WorkflowStore, close_workflow_stores, get_workflow_store
from teleclaude.paths import PROJECTS_MANIFEST_PATH

_GITHUB_UNREACHABLE = frozenset(
    {
        GitHubIdentityRefusal.CREDENTIAL_REFUSED,
        GitHubIdentityRefusal.RATE_LIMITED,
        GitHubIdentityRefusal.PROVIDER_UNAVAILABLE,
    }
)


def _github_identity_refusal_detail(reason: GitHubIdentityRefusal, project_root: Path) -> str:
    """Name a GitHub workflow-store refusal in plain words and the act that resolves it."""
    if reason is GitHubIdentityRefusal.UNREGISTERED_PROJECT:
        return (
            f"{project_root} is not a registered project in {PROJECTS_MANIFEST_PATH}. "
            "Register it by running `telec config project adopt` from that folder."
        )
    if reason in _GITHUB_UNREACHABLE:
        return f"the GitHub workflow store could not be reached ({reason}). Retry, or check `telec app status`."
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
        print(f"Error: {_github_identity_refusal_detail(refused.reason, project_root)}", file=sys.stderr)
        raise SystemExit(1) from refused
