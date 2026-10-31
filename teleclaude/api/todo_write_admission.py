"""The one admission every todo write shares: an item awaiting republication refuses it before anything else."""

from __future__ import annotations

import json
from collections.abc import Mapping
from http import HTTPMethod
from typing import Final, cast

from fastapi import Depends, Request

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.config.machine import config
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_store import GitHubWorkflowStore
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.project_root import resolve_project_root

_READ_METHODS: Final = frozenset({HTTPMethod.GET, HTTPMethod.HEAD, HTTPMethod.OPTIONS})
_SLUG: Final = "slug"
_TODO_ID: Final = "todo_id"
_CWD: Final = "cwd"
_PROJECT_PATH: Final = "project_path"


async def admit_item_write(request: Request, _identity: CallerIdentity = Depends(carried_caller)) -> None:
    """Refuse a write to an item the GitHub store still awaits republication for, ahead of every other answer.

    Router dependency of every todo write route. The item is the slug or id the request addresses, in its path or
    JSON body; the project is the request's `cwd` or `project_path`, or the computer's default working directory.
    The store resolves the live item once and records its write as requested, so a route's own missing-item or
    missing-state answer never precedes the retryable refusal. A slug no live item bears is a creation key or an
    unknown name, and a project outside the GitHub store has no such state: both pass unchanged.
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
    if await store.admit_write(
        slug=slug if isinstance(slug, str) else None, todo_id=todo_id if isinstance(todo_id, str) else None
    ):
        raise GitHubIORefused(GitHubIOFailure.AWAITING_REPUBLICATION)


async def _body_address(request: Request) -> tuple[str | None, str | None]:
    """The slug and project a JSON body names; a body that is not a JSON object names neither."""
    raw = await request.body()
    if not raw:
        return None, None
    try:
        decoded: object = json.loads(raw)
    except ValueError:
        return None, None
    if not isinstance(decoded, dict):
        return None, None
    fields = cast(Mapping[str, object], decoded)
    slug = fields.get(_SLUG)
    project = fields.get(_CWD) or fields.get(_PROJECT_PATH)
    return (slug if isinstance(slug, str) else None, project if isinstance(project, str) else None)
