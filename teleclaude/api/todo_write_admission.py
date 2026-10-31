"""The one admission every todo write shares: an item awaiting republication refuses it before anything else."""

from __future__ import annotations

import json
from typing import Final

from fastapi import Depends, Request

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.config.machine import config
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_store import GitHubWorkflowStore
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.project_root import resolve_project_root

_READ_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
_SLUG: Final = "slug"
_TODO_ID: Final = "todo_id"
_CWD: Final = "cwd"


async def admit_item_write(request: Request, _identity: CallerIdentity = Depends(carried_caller)) -> None:
    """Refuse a write to an item the GitHub store still awaits republication for, ahead of every other answer.

    Router dependency of every todo write route. The item is the slug or id the request addresses, in its path or
    JSON body; the project is the request's `cwd`, or the computer's default working directory. The store resolves
    the identity once, so a route's own missing-item or missing-state answer never precedes the retryable refusal.
    A request that addresses no existing item, or a project outside the GitHub store, passes unchanged.
    """
    if request.method in _READ_METHODS:
        return
    body_slug, body_cwd = await _body_address(request)
    slug = request.path_params.get(_SLUG) or body_slug
    todo_id = request.path_params.get(_TODO_ID)
    if not isinstance(slug, str) and not isinstance(todo_id, str):
        return
    cwd = request.query_params.get(_CWD) or body_cwd or config.computer.default_working_dir
    try:
        project_root = resolve_project_root(str(cwd))
    except FileNotFoundError:
        return
    store = await get_workflow_store(project_root)
    if not isinstance(store, GitHubWorkflowStore):
        return
    if await store.awaiting_republication(
        slug=slug if isinstance(slug, str) else None, todo_id=todo_id if isinstance(todo_id, str) else None
    ):
        raise GitHubIORefused(GitHubIOFailure.AWAITING_REPUBLICATION)


async def _body_address(request: Request) -> tuple[str | None, str | None]:
    """The slug and project directory a JSON body names; a body that is not a JSON object names neither."""
    raw = await request.body()
    if not raw:
        return None, None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    slug, cwd = parsed.get(_SLUG), parsed.get(_CWD)
    return (slug if isinstance(slug, str) else None, cwd if isinstance(cwd, str) else None)
