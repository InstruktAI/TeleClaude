"""The one computer a GitHub-backed project's lifecycle runs on, named in a repository variable.

The project's repository carries the variable, so every computer with a checkout reads the same answer from GitHub
and no computer depends on another to learn it (``local/projects/teleclaude/spec/feature/workflow/driver-admission``).
Only a deliberate act writes it; its last-writer-wins update is therefore enough. Every read asks GitHub, so a
completed handoff governs the next admission decision on every computer.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Any, Final, cast

from githubkit_schemas.v2026_03_10.types import AppPermissionsType

from teleclaude.core.workflow_store.github_io_models import GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused, GitHubTransport
from teleclaude.core.workflow_store.github_io_unit import submit_serialized_unit
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


class _Access(StrEnum):
    READ = "read"
    WRITE = "write"


_READ_PERMISSIONS: Final = cast(AppPermissionsType, {_VARIABLES_PERMISSION: _Access.READ})
_WRITE_PERMISSIONS: Final = cast(AppPermissionsType, {_VARIABLES_PERMISSION: _Access.WRITE})
_VARIABLE_PATH: Final = "/repos/{repository}/actions/variables/{name}"
_VARIABLES_PATH: Final = "/repos/{repository}/actions/variables"
_NAME_FIELD: Final = "name"
_VALUE_FIELD: Final = "value"


# One transport per repository, so its installation token is reused rather than issued for every read.
_transports: dict[GitHubRepositoryScope, GitHubTransport] = {}


def _scope(project_root: Path) -> tuple[GitHubTransport, str, GitHubActorAssignment]:
    _root, identity, assignment = resolve_github_store_selection(project_root)
    scope = GitHubRepositoryScope(identity.repository_id, identity.repository)
    transport = _transports.setdefault(scope, GitHubTransport(scope))
    return transport, identity.repository, assignment


async def read_active_computer(project_root: Path) -> str | None:
    """The computer the project names as active, or ``None`` when it names none. Raises ``GitHubIORefused``.

    It runs as a unit on the shared GitHub I/O loop, which owns the process-wide request gate.
    """
    return await asyncio.wrap_future(submit_serialized_unit(partial(_read, project_root)))


async def write_active_computer(project_root: Path, computer: str) -> None:
    """Name ``computer`` as the project's active computer. Raises ``GitHubIORefused``.

    It runs as a unit on the shared GitHub I/O loop, which owns the process-wide request gate.
    """
    await asyncio.wrap_future(submit_serialized_unit(partial(_write, project_root, computer)))


async def _read(project_root: Path) -> str | None:
    transport, repository, assignment = _scope(project_root)
    path = _VARIABLE_PATH.format(repository=repository, name=ACTIVE_COMPUTER_VARIABLE)

    async def read(client: Any) -> str | None:  # guard: any-type - githubkit's client is generic over its auth
        response = await client.arequest(_Method.GET, path)
        value = response.json().get(_VALUE_FIELD)
        return value if isinstance(value, str) and value else None

    try:
        return await transport.call(assignment, _READ_PERMISSIONS, _Operation.READ, read)
    except GitHubIORefused as refused:
        if refused.reason is not GitHubIOFailure.NOT_FOUND:
            raise
        return None


async def _write(project_root: Path, computer: str) -> None:
    transport, repository, assignment = _scope(project_root)
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
