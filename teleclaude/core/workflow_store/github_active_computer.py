"""The one computer a GitHub-backed project's lifecycle runs on, named in a repository variable.

The project's repository carries the variable, so every computer with a checkout reads the same answer from GitHub
and no computer depends on another to learn it (``local/projects/teleclaude/spec/feature/workflow/driver-admission``).
Only a deliberate act writes it; its last-writer-wins update is therefore enough. A read is cached briefly, because
every start, release and runner pass of the project asks.
"""

from __future__ import annotations

import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, cast

from githubkit_schemas.v2026_03_10.types import AppPermissionsType

from teleclaude.core.workflow_store.github_io_models import GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused, GitHubTransport
from teleclaude.core.workflow_store.github_store import resolve_github_store_selection
from teleclaude.types.github_binding import GitHubActorAssignment

ACTIVE_COMPUTER_VARIABLE: Final = "TELECLAUDE_ACTIVE_COMPUTER"


class _Operation(StrEnum):
    READ = "read_active_computer"
    UPDATE = "update_active_computer"
    CREATE = "create_active_computer"


class _Method(StrEnum):
    GET = "GET"
    PATCH = "PATCH"
    POST = "POST"


# The repository "Variables" permission; the typed permission schema in use predates it.
_VARIABLES_PERMISSION: Final = "actions_variables"
_READ: Final = "read"
_WRITE: Final = "write"
_READ_PERMISSIONS: Final = cast(AppPermissionsType, {_VARIABLES_PERMISSION: _READ})
_WRITE_PERMISSIONS: Final = cast(AppPermissionsType, {_VARIABLES_PERMISSION: _WRITE})
_VARIABLE_PATH: Final = "/repos/{repository}/actions/variables/{name}"
_VARIABLES_PATH: Final = "/repos/{repository}/actions/variables"
_NAME_FIELD: Final = "name"
_VALUE_FIELD: Final = "value"
# Long enough that a burst of starts and a runner pass share one read, short enough that a change lands quickly.
_CACHE_SECONDS: Final = 30.0
_cache: dict[Path, tuple[str | None, float]] = {}


def _scope(project_root: Path) -> tuple[Path, GitHubTransport, str, GitHubActorAssignment]:
    root, identity, assignment = resolve_github_store_selection(project_root)
    transport = GitHubTransport(GitHubRepositoryScope(identity.repository_id, identity.repository))
    return root, transport, identity.repository, assignment


async def read_active_computer(project_root: Path) -> str | None:
    """The computer the project names as active, or ``None`` when it names none. Raises ``GitHubIORefused``."""
    root, transport, repository, assignment = _scope(project_root)
    cached = _cache.get(root)
    if cached is not None and cached[1] > time.monotonic():
        return cached[0]
    path = _VARIABLE_PATH.format(repository=repository, name=ACTIVE_COMPUTER_VARIABLE)

    async def read(client: Any) -> str | None:  # guard: any-type - githubkit's client is generic over its auth
        response = await client.arequest(_Method.GET, path)
        value = response.json().get(_VALUE_FIELD)
        return value if isinstance(value, str) and value else None

    try:
        active = await transport.call(assignment, _READ_PERMISSIONS, _Operation.READ, read)
    except GitHubIORefused as refused:
        if refused.reason is not GitHubIOFailure.NOT_FOUND:
            raise
        active = None
    _cache[root] = (active, time.monotonic() + _CACHE_SECONDS)
    return active


async def write_active_computer(project_root: Path, computer: str) -> None:
    """Name ``computer`` as the project's active computer. Raises ``GitHubIORefused``."""
    root, transport, repository, assignment = _scope(project_root)
    body = {_NAME_FIELD: ACTIVE_COMPUTER_VARIABLE, _VALUE_FIELD: computer}
    variable = _VARIABLE_PATH.format(repository=repository, name=ACTIVE_COMPUTER_VARIABLE)
    variables = _VARIABLES_PATH.format(repository=repository)

    async def update(client: Any) -> None:  # guard: any-type - githubkit's client is generic over its auth
        await client.arequest(_Method.PATCH, variable, json=body)

    async def create(client: Any) -> None:  # guard: any-type - githubkit's client is generic over its auth
        await client.arequest(_Method.POST, variables, json=body)

    try:
        await transport.call(assignment, _WRITE_PERMISSIONS, _Operation.UPDATE, update)
    except GitHubIORefused as refused:
        if refused.reason is not GitHubIOFailure.NOT_FOUND:
            raise
        await transport.call(assignment, _WRITE_PERMISSIONS, _Operation.CREATE, create)
    _cache[root] = (computer, time.monotonic() + _CACHE_SECONDS)
