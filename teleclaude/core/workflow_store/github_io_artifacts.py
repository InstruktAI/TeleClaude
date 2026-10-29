"""Issue-artifact requests of the GitHub preview REST API and the closed values read from their responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from githubkit.exception import RequestFailed

from teleclaude.core.workflow_store.github_io_fields import GitHubField
from teleclaude.core.workflow_store.github_io_models import (
    GitHubActor,
    GitHubArtifact,
    GitHubArtifactHistory,
    GitHubArtifactVersion,
)
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused, split_repository

__all__ = [
    "create_artifact",
    "delete_artifact",
    "list_artifacts",
    "read_artifact",
    "update_artifact",
]

_PAGE_SIZE = 100
_EMPTY = ""
_ARTIFACTS_PATH = "/repos/{}/{}/issues/{}/artifacts"
_ARTIFACT_PATH = "/repos/{}/{}/issues/{}/artifacts/{}"
_ARTIFACT_API_VERSION = "2026-03-10"
_ARTIFACT_NOT_SERVED = (404, 410)
_TIMESTAMP_UTC_SUFFIX = "Z"
_TIMESTAMP_UTC_OFFSET = "+00:00"


class _Verb(StrEnum):
    GET = "GET"
    POST = "POST"
    PATCH = "PATCH"
    DELETE = "DELETE"


_HEADERS = {GitHubField.API_VERSION_HEADER.value: _ARTIFACT_API_VERSION}
Pace = Callable[[], Awaitable[None]]


async def list_artifacts(
    client: Any, repository: str, number: int, artifact_type: str | None, first_page_size: int | None
) -> tuple[GitHubArtifact, ...]:
    """List an issue's artifacts with their current bodies; `first_page_size` reads that many in one request."""
    path = _collection_path(repository, number)
    page_size = first_page_size if first_page_size is not None else _PAGE_SIZE
    found: list[GitHubArtifact] = []
    page = 1
    while True:
        params: dict[str, str | int] = {GitHubField.PER_PAGE: page_size, GitHubField.PAGE: page}
        if artifact_type is not None:
            params[GitHubField.TYPE] = artifact_type
        try:
            response = await client.arequest(_Verb.GET, path, params=params, headers=_HEADERS)
        except RequestFailed as error:
            raise _collection_refusal(error) from None
        payload = response.json()
        if not isinstance(payload, list):
            raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
        found.extend(_artifact(entry) for entry in payload)
        if first_page_size is not None or len(payload) < page_size:
            return tuple(found)
        page += 1


async def read_artifact(client: Any, repository: str, number: int, artifact_number: int) -> GitHubArtifactHistory:
    """Read one artifact with the newest versions GitHub still serves."""
    response = await client.arequest(_Verb.GET, _item_path(repository, number, artifact_number), headers=_HEADERS)
    payload = response.json()
    if not isinstance(payload, dict):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    versions = payload.get(GitHubField.VERSIONS)
    if not isinstance(versions, list):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    return GitHubArtifactHistory(
        _artifact(payload.get(GitHubField.ARTIFACT)), tuple(_version(entry) for entry in versions)
    )


async def create_artifact(
    client: Any, repository: str, number: int, artifact_type: str, name: str, body: str, pace: Pace
) -> GitHubArtifact:
    await pace()
    try:
        response = await client.arequest(
            _Verb.POST,
            _collection_path(repository, number),
            json={GitHubField.TYPE: artifact_type, GitHubField.NAME: name, GitHubField.BODY: body},
            headers=_HEADERS,
        )
    except RequestFailed as error:
        raise _collection_refusal(error) from None
    return _artifact(response.json())


async def update_artifact(
    client: Any, repository: str, number: int, artifact_number: int, body: str, pace: Pace
) -> GitHubArtifact:
    """Save `body` as the artifact's next version."""
    await pace()
    response = await client.arequest(
        _Verb.PATCH, _item_path(repository, number, artifact_number), json={GitHubField.BODY: body}, headers=_HEADERS
    )
    return _artifact(response.json())


async def delete_artifact(client: Any, repository: str, number: int, artifact_number: int, pace: Pace) -> None:
    await pace()
    await client.arequest(_Verb.DELETE, _item_path(repository, number, artifact_number), headers=_HEADERS)


def _collection_path(repository: str, number: int) -> str:
    owner, repo = split_repository(repository)
    return _ARTIFACTS_PATH.format(owner, repo, number)


def _item_path(repository: str, number: int, artifact_number: int) -> str:
    owner, repo = split_repository(repository)
    return _ARTIFACT_PATH.format(owner, repo, number, artifact_number)


def _collection_refusal(error: RequestFailed) -> GitHubIORefused | RequestFailed:
    """A repository that does not serve artifacts answers a collection read or create with 404 or 410."""
    if error.response.status_code in _ARTIFACT_NOT_SERVED:
        return GitHubIORefused(GitHubIOFailure.ISSUE_ARTIFACTS_UNAVAILABLE)
    return error


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace(_TIMESTAMP_UTC_SUFFIX, _TIMESTAMP_UTC_OFFSET))


def _actor(value: object) -> GitHubActor | None:
    if not isinstance(value, dict):
        return None
    actor_id = value.get(GitHubField.ID)
    login = value.get(GitHubField.LOGIN)
    if not isinstance(actor_id, int) or not isinstance(login, str):
        return None
    return GitHubActor(actor_id, login)


def _artifact(entry: object) -> GitHubArtifact:
    if not isinstance(entry, dict):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    number = entry.get(GitHubField.NUMBER)
    artifact_type = entry.get(GitHubField.TYPE)
    name = entry.get(GitHubField.NAME)
    body = entry.get(GitHubField.BODY)
    if not isinstance(number, int) or not isinstance(artifact_type, str) or not isinstance(name, str):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    return GitHubArtifact(
        number,
        artifact_type,
        name,
        body if isinstance(body, str) else _EMPTY,
        _actor(entry.get(GitHubField.CREATOR)),
        _actor(entry.get(GitHubField.UPDATED_BY_ACTOR)),
        _timestamp(entry.get(GitHubField.CREATED_AT)),
        _timestamp(entry.get(GitHubField.UPDATED_AT)),
    )


def _version(entry: object) -> GitHubArtifactVersion:
    if not isinstance(entry, dict):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    version = entry.get(GitHubField.VERSION)
    name = entry.get(GitHubField.NAME)
    body = entry.get(GitHubField.BODY)
    if not isinstance(version, int) or not isinstance(name, str):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    return GitHubArtifactVersion(
        version,
        name,
        body if isinstance(body, str) else _EMPTY,
        _timestamp(entry.get(GitHubField.CREATED_AT)),
        _actor(entry.get(GitHubField.ACTOR)),
    )
