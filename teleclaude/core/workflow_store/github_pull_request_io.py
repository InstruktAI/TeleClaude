"""Pull request and review requests for one repository, made as the builder and reviewer Apps."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from enum import StrEnum
from functools import partial
from typing import Any, TypeVar

from githubkit_schemas.v2026_03_10.types import AppPermissionsType

from teleclaude.config.loader import github_actor_for_role
from teleclaude.core.roles import RoleName
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_io_models import (
    GitHubPullRequest,
    GitHubRepositoryScope,
    GitHubReview,
)
from teleclaude.core.workflow_store.github_io_transport import (
    GitHubIOFailure,
    GitHubIORefused,
    GitHubTransport,
    split_repository,
)
from teleclaude.core.workflow_store.github_io_unit import submit_serialized_unit
from teleclaude.types.github_binding import GitHubActorAssignment

_PAGE_SIZE = 100
_REPOSITORY_SEPARATOR = "/"
_HEAD_TEMPLATE = "{owner}:{branch}"
_EMPTY = ""
_PULL_REQUEST_PERMISSIONS: AppPermissionsType = {"pull_requests": "write"}
_Result = TypeVar("_Result")


class GitHubPullRequestOperation(StrEnum):
    """Closed set of provider operations made for pull requests, named in refusals."""

    DEFAULT_BRANCH = "default_branch"
    LIST_PULL_REQUESTS = "list_pull_requests"
    CREATE_PULL_REQUEST = "create_pull_request"
    UPDATE_PULL_REQUEST = "update_pull_request"
    CLOSE_PULL_REQUEST = "close_pull_request"
    COMMENT_PULL_REQUEST = "comment_pull_request"
    LIST_COMMENTS = "list_comments"
    LIST_REVIEWS = "list_reviews"
    CREATE_REVIEW = "create_review"


class GitHubReviewEvent(StrEnum):
    """Review verdict events GitHub accepts for a submitted review."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class GitHubPullRequestField(StrEnum):
    """GitHub REST field names used by the pull request requests."""

    TITLE = "title"
    BODY = "body"
    HEAD = "head"
    BASE = "base"
    DRAFT = "draft"
    STATE = "state"
    COMMIT_ID = "commit_id"
    EVENT = "event"
    CLOSED = "closed"
    OPEN = "open"
    ALL_STATES = "all"


def _pull_request(pull: Any) -> GitHubPullRequest:
    return GitHubPullRequest(
        number=pull.number,
        node_id=pull.node_id,
        author=pull.user.login if pull.user is not None else _EMPTY,
        title=pull.title,
        body=pull.body or _EMPTY,
        draft=bool(pull.draft),
        open=pull.state == GitHubPullRequestField.OPEN,
        head_branch=pull.head.ref,
    )


class GitHubPullRequestIO:
    """Make pull request requests for one repository.

    The pull request is opened, edited and closed as the App mapped to `builder` and
    reviewed as the App mapped to `reviewer`: GitHub refuses approving or
    requesting changes on a pull request from its own author. Every primitive runs
    inside `submit`, which holds the unit lock for the whole unit; each primitive's
    request takes the process-wide request lock alone, like every store request.
    """

    def __init__(self, repository: GitHubRepositoryIdentity) -> None:
        self.repository = repository
        self._transport = GitHubTransport(GitHubRepositoryScope(repository.repository_id, repository.repository))

    def submit(self, work: Callable[[GitHubPullRequestIO], Awaitable[_Result]]) -> Future[_Result]:
        """Queue one serialized unit of pull request work on the shared GitHub I/O loop."""
        return submit_serialized_unit(partial(work, self))

    async def reviewer_login(self) -> str:
        """Return the login the reviewer App's reviews are authored under."""
        return (await self._assignment(RoleName.REVIEWER)).actor.login

    async def default_branch(self) -> str:
        """Return the repository's default branch, the base of every item's pull request."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> str:
            response = await client.rest.repos.async_get(owner, repo)
            return str(response.parsed_data.default_branch)

        return await self._request(RoleName.BUILDER, GitHubPullRequestOperation.DEFAULT_BRANCH, request)

    async def list_pull_requests(self, branch: str) -> tuple[GitHubPullRequest, ...]:
        """List the builder App's pull requests whose head is `branch`, open or closed."""
        owner, repo = split_repository(self.repository.repository)
        head = _HEAD_TEMPLATE.format(
            owner=self.repository.repository.partition(_REPOSITORY_SEPARATOR)[0], branch=branch
        )
        builder = await self._assignment(RoleName.BUILDER)

        async def request(client: Any) -> tuple[GitHubPullRequest, ...]:
            found: list[GitHubPullRequest] = []
            page = 1
            while True:
                response = await client.rest.pulls.async_list(
                    owner, repo, state=GitHubPullRequestField.ALL_STATES, head=head, per_page=_PAGE_SIZE, page=page
                )
                pulls = response.parsed_data
                found.extend(
                    _pull_request(pull)
                    for pull in pulls
                    if pull.user is not None and pull.user.login == builder.actor.login
                )
                if len(pulls) < _PAGE_SIZE:
                    return tuple(found)
                page += 1

        return await self._transport.call(
            builder, _PULL_REQUEST_PERMISSIONS, GitHubPullRequestOperation.LIST_PULL_REQUESTS, request
        )

    async def create_draft_pull_request(self, title: str, body: str, branch: str, base: str) -> GitHubPullRequest:
        """Open a draft pull request from `branch` into `base`; a draft cannot be merged on GitHub."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> GitHubPullRequest:
            response = await client.rest.pulls.async_create(
                owner,
                repo,
                data={
                    GitHubPullRequestField.TITLE.value: title,
                    GitHubPullRequestField.BODY.value: body,
                    GitHubPullRequestField.HEAD.value: branch,
                    GitHubPullRequestField.BASE.value: base,
                    GitHubPullRequestField.DRAFT.value: True,
                },
            )
            return _pull_request(response.parsed_data)

        return await self._request(RoleName.BUILDER, GitHubPullRequestOperation.CREATE_PULL_REQUEST, request)

    async def update_pull_request(self, number: int, title: str, body: str) -> None:
        """Rewrite a pull request's title and body."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await client.rest.pulls.async_update(
                owner,
                repo,
                number,
                data={GitHubPullRequestField.TITLE.value: title, GitHubPullRequestField.BODY.value: body},
            )

        await self._request(RoleName.BUILDER, GitHubPullRequestOperation.UPDATE_PULL_REQUEST, request)

    async def comment_on_pull_request(self, number: int, body: str) -> None:
        """Comment on a pull request through the issue comments of its number."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await client.rest.issues.async_create_comment(
                owner, repo, number, data={GitHubPullRequestField.BODY.value: body}
            )

        await self._request(RoleName.BUILDER, GitHubPullRequestOperation.COMMENT_PULL_REQUEST, request)

    async def close_pull_request(self, number: int) -> None:
        """Close a pull request without merging it."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await client.rest.pulls.async_update(
                owner, repo, number, data={GitHubPullRequestField.STATE.value: GitHubPullRequestField.CLOSED.value}
            )

        await self._request(RoleName.BUILDER, GitHubPullRequestOperation.CLOSE_PULL_REQUEST, request)

    async def list_own_comments(self, number: int) -> tuple[str, ...]:
        """List the bodies of the comments the builder App wrote on a pull request."""
        owner, repo = split_repository(self.repository.repository)
        builder = await self._assignment(RoleName.BUILDER)

        async def request(client: Any) -> tuple[str, ...]:
            found: list[str] = []
            page = 1
            while True:
                response = await client.rest.issues.async_list_comments(
                    owner, repo, number, per_page=_PAGE_SIZE, page=page
                )
                comments = response.parsed_data
                found.extend(
                    comment.body or _EMPTY
                    for comment in comments
                    if comment.user is not None and comment.user.login == builder.actor.login
                )
                if len(comments) < _PAGE_SIZE:
                    return tuple(found)
                page += 1

        return await self._transport.call(
            builder, _PULL_REQUEST_PERMISSIONS, GitHubPullRequestOperation.LIST_COMMENTS, request
        )

    async def list_reviews(self, number: int) -> tuple[GitHubReview, ...]:
        """List the submitted reviews of a pull request, whoever posted them."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> tuple[GitHubReview, ...]:
            found: list[GitHubReview] = []
            page = 1
            while True:
                response = await client.rest.pulls.async_list_reviews(
                    owner, repo, number, per_page=_PAGE_SIZE, page=page
                )
                reviews = response.parsed_data
                found.extend(
                    GitHubReview(
                        review_id=review.id,
                        author=review.user.login if review.user is not None else _EMPTY,
                        commit_id=review.commit_id or _EMPTY,
                        state=review.state,
                        body=review.body,
                    )
                    for review in reviews
                )
                if len(reviews) < _PAGE_SIZE:
                    return tuple(found)
                page += 1

        return await self._request(RoleName.REVIEWER, GitHubPullRequestOperation.LIST_REVIEWS, request)

    async def create_review(self, number: int, commit_id: str, event: GitHubReviewEvent, body: str) -> None:
        """Submit one review bound to `commit_id` as the reviewer App."""
        owner, repo = split_repository(self.repository.repository)

        async def request(client: Any) -> None:
            await client.rest.pulls.async_create_review(
                owner,
                repo,
                number,
                data={
                    GitHubPullRequestField.COMMIT_ID.value: commit_id,
                    GitHubPullRequestField.EVENT.value: event.value,
                    GitHubPullRequestField.BODY.value: body,
                },
            )

        await self._request(RoleName.REVIEWER, GitHubPullRequestOperation.CREATE_REVIEW, request)

    async def _request(
        self, role: RoleName, operation: GitHubPullRequestOperation, request: Callable[[Any], Awaitable[_Result]]
    ) -> _Result:
        assignment = await self._assignment(role)
        return await self._transport.call(assignment, _PULL_REQUEST_PERMISSIONS, operation, request)

    async def _assignment(self, role: RoleName) -> GitHubActorAssignment:
        assignment = await asyncio.to_thread(github_actor_for_role, role)
        if assignment is None:
            raise GitHubIORefused(GitHubIOFailure.ROLE_UNMAPPED, detail=role.value)
        return assignment
