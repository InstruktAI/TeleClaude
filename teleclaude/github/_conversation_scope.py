"""Join native conversation to existing immutable PR/object authority, never a new relationship producer."""

from __future__ import annotations

from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.db import get_db
from teleclaude.core.github_identity import GitHubPostingContext, resolve_native_github_posting_context
from teleclaude.github._pr_provider import pr_reader, verify_pr_membership
from teleclaude.github.credentials import GitHubInstallationCredential
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubObjectAssociation,
    GitHubObjectKind,
    GitHubObjectRef,
    GitHubPostFailure,
    GitHubPostResult,
    NativeGitHubPostSource,
)


async def resolve_pr_scope(context: GitHubPostingContext, number: int) -> GitHubObjectAssociation | None:
    """An exact existing relationship survives a historical creator closing; absence supplies no replacement."""
    try:
        store = await get_db()
        scope = await store.find_github_pr_association(context.target.repository_id, number)
    except (SQLAlchemyError, OSError, ValueError):
        return None
    if (
        scope is None
        or scope.object.kind is not GitHubObjectKind.PULL_REQUEST
        or scope.object.repository_id != context.target.repository_id
        or scope.object.container_number != number
        or scope.work_issue_number != context.target.issue_number
        or scope.pull_request is None
    ):
        return None
    return scope


async def requested_pr_scope(
    context: GitHubPostingContext,
    ref: GitHubObjectRef | None,
) -> tuple[bool, GitHubObjectAssociation | None]:
    """Absent PR scope selects the bound work issue; a supplied reference must match existing authority."""
    if ref is None:
        return True, None
    scope = await resolve_pr_scope(context, ref.container_number)
    return scope is not None and scope.object == ref, scope


def _native_creator_matches(context: GitHubPostingContext, creation: GitHubObjectAssociation) -> bool:
    """Same App or prose is insufficient: maintenance belongs to the exact recorded native writer."""
    return (
        creation.object.kind in (GitHubObjectKind.ISSUE_COMMENT, GitHubObjectKind.REVIEW)
        and creation.object.repository_id == context.target.repository_id
        and creation.work_issue_number == context.target.issue_number
        and isinstance(creation.source, NativeGitHubPostSource)
        and creation.session_id == context.binding.session_id
        and creation.role is context.binding.role
        and creation.actor.same_account(context.binding.assignment.actor)
    )


async def resolve_native_comment(
    context: GitHubPostingContext,
    provider_id: int,
) -> tuple[GitHubObjectAssociation, GitHubObjectAssociation | None] | None:
    """Resolve the explicit canonical object's recorded container before credentials or prose collection."""
    return await _resolve_native_object(context, provider_id, GitHubObjectKind.ISSUE_COMMENT)


async def resolve_native_review(
    context: GitHubPostingContext, provider_id: int
) -> tuple[GitHubObjectAssociation, GitHubObjectAssociation] | None:
    """A review always belongs to an existing PR relationship and this exact native writer."""
    resolved = await _resolve_native_object(context, provider_id, GitHubObjectKind.REVIEW)
    if resolved is None or resolved[1] is None:
        return None
    return resolved[0], resolved[1]


async def _resolve_native_object(
    context: GitHubPostingContext, provider_id: int, kind: GitHubObjectKind
) -> tuple[GitHubObjectAssociation, GitHubObjectAssociation | None] | None:
    try:
        store = await get_db()
        creation = await store.find_github_object_association(
            context.target.repository_id,
            kind,
            provider_id,
        )
    except (SQLAlchemyError, OSError, ValueError):
        return None
    if creation is None or not _native_creator_matches(context, creation):
        return None
    if kind is GitHubObjectKind.ISSUE_COMMENT and creation.object.container_number == context.target.issue_number:
        return creation, None
    scope = await resolve_pr_scope(context, creation.object.container_number)
    return (creation, scope) if scope is not None else None


async def preflight_pr_scope(
    context: GitHubPostingContext,
    scope: GitHubObjectAssociation,
    credential: GitHubInstallationCredential,
) -> GitHubPostResult | None:
    """Verify actual provider membership and original PR author; the current writer has its own fixed actor."""
    try:
        current = await resolve_pr_scope(context, scope.object.container_number)
        if current is None or not current.same_creation(scope):
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.PREFLIGHT_FAILED)
        async with pr_reader(credential) as (reader, client):
            data = await reader.get(client, scope.object.container_number)
            verify_pr_membership(data, context, scope)
        current = await resolve_pr_scope(context, scope.object.container_number)
        if (
            current is None
            or not current.same_creation(scope)
            or await resolve_native_github_posting_context() != context
        ):
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.PREFLIGHT_FAILED)
        return None
    except (GitHubException, OSError, ValueError, TimeoutError, SQLAlchemyError) as error:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.NO_EFFECT,
            failure=GitHubPostFailure.PREFLIGHT_FAILED,
            provider_status=error.response.status_code if isinstance(error, RequestFailed) else None,
            retry_after=error.retry_after if isinstance(error, RateLimitExceeded) else None,
        )
