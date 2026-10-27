"""Conversation requests for one repository, made as the role Apps and never as the App that writes the record.

A conversation comment goes on an issue or a pull request through the issue comments of its number, as the App
mapped to the session's role. Every request here is one GitHub request, so the caller that owns the request budget
admits each one on its own; a listing is read one page at a time for that reason.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from githubkit_schemas.v2026_03_10.types import AppPermissionsType

from teleclaude.config.loader import github_actor_for_app_id, github_actor_for_role
from teleclaude.core.roles import RoleName, composite_role
from teleclaude.core.workflow_store.github_io_models import GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_runtime import shared_github_io_loop
from teleclaude.core.workflow_store.github_io_transport import (
    GitHubIOFailure,
    GitHubIORefused,
    GitHubTransport,
    run_serialized_unit,
    split_repository,
)
from teleclaude.types.github_binding import GitHubActorAssignment

PAGE_SIZE = 100
_EMPTY = ""
_BODY_FIELD = "body"
_UNIT_DETAIL = "conversation unit exceeded its time bound"
_CONVERSATION_PERMISSIONS: AppPermissionsType = {"issues": "write", "pull_requests": "write"}


class GitHubConversationOperation(StrEnum):
    """Closed set of provider operations made for the conversation, named in refusals."""

    CREATE_COMMENT = "create_conversation_comment"
    LIST_COMMENTS = "list_conversation_comments"


@dataclass(frozen=True)
class ConversationComment:
    """One comment an App wrote on an issue or pull request."""

    comment_id: int
    body: str


@dataclass(frozen=True)
class ConversationCommentPage:
    """One page of an App's comments on a destination, oldest first, and whether more pages follow."""

    comments: tuple[ConversationComment, ...]
    has_more: bool


async def conversation_assignment_for_role(role: RoleName) -> GitHubActorAssignment:
    """The App a session's turns are posted as.

    A review role posts as the App mapped for the reviewer role, through its composite role. Every other role posts
    as the App mapped for that role when one is, and otherwise as the App mapped for the builder, the author
    identity. The App that writes the record is mapped to no role and so is never chosen.
    """
    candidates = (RoleName.REVIEWER,) if composite_role(role) is RoleName.REVIEWER else (role, RoleName.BUILDER)
    for candidate in candidates:
        assignment = await asyncio.to_thread(github_actor_for_role, candidate)
        if assignment is not None:
            return assignment
    raise GitHubIORefused(GitHubIOFailure.ROLE_UNMAPPED, detail=role.value)


async def conversation_assignment_for_app(app_id: int) -> GitHubActorAssignment:
    """The declared App with this id, for a request that names the App its sender chose."""
    assignment = await asyncio.to_thread(github_actor_for_app_id, app_id)
    if assignment is None:
        raise GitHubIORefused(GitHubIOFailure.ROLE_UNMAPPED, detail=str(app_id))
    return assignment


class GitHubConversationIO:
    """Make conversation requests for one repository as a given role App."""

    def __init__(self, scope: GitHubRepositoryScope) -> None:
        self.scope = scope
        self._transport = GitHubTransport(scope, secondary_limit_is_rate_limit=True)

    def submit[Result](self, work: Callable[[GitHubConversationIO], Awaitable[Result]]) -> Future[Result]:
        """Queue one serialized unit of conversation work on the shared GitHub I/O loop."""
        return shared_github_io_loop().submit(self._serialized(work))

    async def _serialized[Result](self, work: Callable[[GitHubConversationIO], Awaitable[Result]]) -> Result:
        return await run_serialized_unit(lambda: work(self), unit_detail=_UNIT_DETAIL)

    async def create_comment(self, assignment: GitHubActorAssignment, number: int, body: str) -> int:
        """Append one comment to the issue or pull request with this number, and return its comment id."""
        owner, repo = split_repository(self.scope.repository)

        async def request(client: Any) -> int:
            response = await client.rest.issues.async_create_comment(owner, repo, number, data={_BODY_FIELD: body})
            return int(response.parsed_data.id)

        return await self._transport.call(
            assignment, _CONVERSATION_PERMISSIONS, GitHubConversationOperation.CREATE_COMMENT, request
        )

    async def list_comments_page(
        self, assignment: GitHubActorAssignment, number: int, page: int
    ) -> ConversationCommentPage:
        """Read one page, oldest first, of the comments this App wrote on the issue or pull request."""
        owner, repo = split_repository(self.scope.repository)

        async def request(client: Any) -> ConversationCommentPage:
            response = await client.rest.issues.async_list_comments(owner, repo, number, per_page=PAGE_SIZE, page=page)
            comments = response.parsed_data
            return ConversationCommentPage(
                comments=tuple(
                    ConversationComment(comment_id=int(comment.id), body=comment.body or _EMPTY)
                    for comment in comments
                    if comment.user is not None and comment.user.login == assignment.actor.login
                ),
                has_more=len(comments) >= PAGE_SIZE,
            )

        return await self._transport.call(
            assignment, _CONVERSATION_PERMISSIONS, GitHubConversationOperation.LIST_COMMENTS, request
        )
