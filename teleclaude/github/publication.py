"""Publish one admitted work head through its fixed App and retain confirmed attribution."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from sqlalchemy.exc import SQLAlchemyError

from teleclaude._git_publication import GitPushCancelled, GitPushObservation, WorkRefSnapshot, push_snapshot
from teleclaude.core.db import get_db
from teleclaude.core.github_identity import (
    GitHubPostingContext,
    ManagedGitHubInvocation,
    resolve_native_github_posting_context,
)
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.git import publication_environment
from teleclaude.github._native_gh import gh_binary
from teleclaude.github._publication_observation import (
    PublicationObservation,
    PublicationObservationCancelled,
    PublicationObservationRefused,
    observe_publication,
)
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.types.github_publication import (
    GitHubBranchPublicationRequest,
    GitHubPublicationFailure,
    GitHubPublicationResult,
    GitHubPublicationState,
    GitHubPushActivityType,
    GitHubPushProof,
)

_EMPTY = ""
_SLASH = "/"
_HEADS = "refs/heads/"
_ZERO = "0" * 40
_REPOSITORY_URL = "https://github.com/{repository}.git"
_PREFIX = "teleclaude-github-publication-"
_BARE = "publication.git"
_GH_CONFIG = "gh"
_GH_TOKEN = "GH_TOKEN"
_GH_CONFIG_DIR = "GH_CONFIG_DIR"
_GH_ENVIRONMENT = {"GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
_CONTENTS_WRITE: AppPermissionsType = {"contents": "write"}
_PUSH_TYPES = frozenset({GitHubPushActivityType.PUSH, GitHubPushActivityType.FORCE_PUSH})
_MAIN = "main"
_MINIMUM_PUSH_LIFETIME = timedelta(seconds=30)
_CANCELLED = "Publication cancelled; known effects are attached without retry authorization"


class GitHubPublicationCancelled(asyncio.CancelledError):
    """Cancellation retains safe available ref/acknowledgment/corroboration facts."""

    def __init__(self, result: GitHubPublicationResult) -> None:
        super().__init__(_CANCELLED)
        self.result = result


def _request_matches(context: GitHubPostingContext, request: GitHubBranchPublicationRequest) -> bool:
    return (
        isinstance(context.invocation, ManagedGitHubInvocation)
        and context.target == request.target
        and context.target.branch == request.branch
        and context.target.base == request.base
        and request.branch != request.base
        and request.branch != _MAIN
        and request.worktree.is_absolute()
        and resolve_owning_checkout(request.worktree) == resolve_owning_checkout(context.target.project_path)
    )


def _corroborate(
    context: GitHubPostingContext,
    request: GitHubBranchPublicationRequest,
    before: PublicationObservation,
    after: PublicationObservation,
) -> GitHubPushProof | None:
    """Membership establishes newly observed only; actual actor comes from the confined credentialed child."""
    previous = {(value.id, value.node_id): value for value in before.activities}
    current = {(value.id, value.node_id): value for value in after.activities}
    if not previous.keys() <= current.keys() or any(current[key] != value for key, value in previous.items()):
        return None
    unseen = [value for key, value in current.items() if key not in previous]
    # Competing transitions or indistinguishable candidates cannot corroborate this update.
    if len(unseen) != 1 or after.head != request.head_sha:
        return None
    activity = unseen[0]
    try:
        activity_type = GitHubPushActivityType(activity.activity_type)
    except ValueError:
        return None
    actor = context.binding.assignment.actor
    if (
        activity.ref != _HEADS + request.branch
        or activity.before != (before.head or _ZERO)
        or activity.after != request.head_sha
        or activity.actor is None
        or activity.actor.id != actor.id
        or activity.actor.node_id != actor.node_id
        or activity.actor.type != actor.type.value
        or (before.head is None and activity_type is not GitHubPushActivityType.BRANCH_CREATION)
        or (before.head is not None and activity_type not in _PUSH_TYPES)
    ):
        return None
    return GitHubPushProof(
        binding=context.binding,
        target=context.target,
        ref=activity.ref,
        before=activity.before,
        after=activity.after,
        activity_id=activity.id,
        activity_node_id=activity.node_id,
        activity_type=activity_type,
        activity_at=activity.timestamp,
        observed_at=datetime.now(UTC),
    )


async def publish_github_work_branch(
    context: GitHubPostingContext,
    request: GitHubBranchPublicationRequest,
) -> GitHubPublicationResult:
    """Connect admission, one native send, bounded observed corroboration and durable attribution."""
    before: PublicationObservation | None = None
    after: PublicationObservation | None = None
    child = GitPushObservation(False)
    candidate: GitHubPushProof | None = None
    phase = GitHubPublicationFailure.CONTEXT
    observing_before = True
    partial_head: str | None = None
    partial_observed = False

    def result(
        state: GitHubPublicationState,
        failure: GitHubPublicationFailure | None = None,
        *,
        proof: GitHubPushProof | None = None,
        tracking: bool | None = None,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> GitHubPublicationResult:
        return GitHubPublicationResult(
            state=state,
            failure=failure,
            desired=request.head_sha,
            before=before.head if before is not None else (partial_head if observing_before else None),
            current=after.head if after is not None else (partial_head if not observing_before else None),
            before_observed=before is not None or (observing_before and partial_observed),
            current_observed=after is not None or (not observing_before and partial_observed),
            child_update_acknowledged=child.acknowledged,
            possible_remote_effect=child.started and not child.noop,
            proof=proof,
            corroboration=candidate,
            tracking_advanced=tracking,
            provider_status=status,
            retry_after_seconds=retry_after,
        )

    try:
        if not _request_matches(context, request) or await resolve_native_github_posting_context() != context:
            return result(GitHubPublicationState.REFUSED, phase)
        phase = GitHubPublicationFailure.HISTORY
        with TemporaryDirectory(prefix=_PREFIX) as temporary:
            root = Path(temporary)
            snapshot = WorkRefSnapshot.capture(
                request.worktree, root / _BARE, request.branch, request.head_sha, request.base
            )
            environment = publication_environment()
            binary = gh_binary(environment)
            if binary is None:
                return result(GitHubPublicationState.REFUSED, GitHubPublicationFailure.CREDENTIAL)
            repository = _SLASH.join(quote(part, safe=_EMPTY) for part in request.target.repository.split(_SLASH))
            snapshot.configure(_REPOSITORY_URL.format(repository=repository), binary)
            config = root / _GH_CONFIG
            config.mkdir(mode=0o700)
            phase = GitHubPublicationFailure.CREDENTIAL
            credential = await issue_github_installation_credential(
                context.binding.assignment, request.target, _CONTENTS_WRITE
            )
            if credential.assignment != context.binding.assignment or credential.target != request.target:
                return result(GitHubPublicationState.REFUSED, phase)
            environment.update(
                {_GH_TOKEN: credential.token.get_secret_value(), _GH_CONFIG_DIR: str(config), **_GH_ENVIRONMENT}
            )
            phase = GitHubPublicationFailure.OBSERVATION
            before = await observe_publication(credential, request.branch, before_send=True)
            if before.head == request.head_sha:
                store = await get_db()
                retained = await store.get_github_push_proofs(context.binding.session_id)
                matching = next(
                    (
                        proof
                        for proof in retained
                        if (
                            proof.binding == context.binding
                            and proof.target == context.target
                            and proof.ref == snapshot.ref
                            and proof.after == request.head_sha
                        )
                    ),
                    None,
                )
                return result(GitHubPublicationState.NOOP, proof=matching)
            if before.head != snapshot.previous_tracking:
                return result(GitHubPublicationState.REFUSED, GitHubPublicationFailure.TRACKING)
            if credential.expires_at <= datetime.now(UTC) + _MINIMUM_PUSH_LIFETIME:
                return result(GitHubPublicationState.REFUSED, GitHubPublicationFailure.CREDENTIAL)
            phase = GitHubPublicationFailure.CONTEXT
            if await resolve_native_github_posting_context() != context or not snapshot.unchanged():
                return result(GitHubPublicationState.REFUSED, phase)
            phase = GitHubPublicationFailure.SEND
            child = await push_snapshot(snapshot, environment)
            phase = GitHubPublicationFailure.OBSERVATION
            observing_before = False
            after = await observe_publication(credential, request.branch, before_send=False)
            if child.noop:
                return result(GitHubPublicationState.NOOP)
            if not child.acknowledged or not child.successful:
                return result(
                    GitHubPublicationState.UNKNOWN if child.started else GitHubPublicationState.REFUSED,
                    GitHubPublicationFailure.SEND,
                )
            phase = GitHubPublicationFailure.ATTRIBUTION
            candidate = _corroborate(context, request, before, after)
            if candidate is None:
                return result(GitHubPublicationState.UNKNOWN, phase)
            # No set subtraction supplies causation or actor authority: the verified credential,
            # confined child acknowledgment and exact current ref establish the actual update;
            # these activity facts are retained solely as observed corroboration.
            phase = GitHubPublicationFailure.RETENTION
            if await resolve_native_github_posting_context() != context:
                return result(GitHubPublicationState.UNKNOWN, phase)
            store = await get_db()
            proof = await store.record_github_push_proof(candidate)
            tracking = snapshot.advance_tracking()
            return result(GitHubPublicationState.CONFIRMED, proof=proof, tracking=tracking)
    except PublicationObservationCancelled as error:
        partial_head, partial_observed = error.head, error.observed
        raise GitHubPublicationCancelled(
            result(
                GitHubPublicationState.UNKNOWN if child.started else GitHubPublicationState.REFUSED,
                GitHubPublicationFailure.CANCELLED,
            )
        ) from None
    except PublicationObservationRefused as error:
        partial_head, partial_observed = error.head, error.observed
        return result(
            GitHubPublicationState.UNKNOWN if child.started else GitHubPublicationState.REFUSED,
            phase,
            status=error.status,
            retry_after=error.retry_after,
        )
    except GitPushCancelled as error:
        child = error.observation
        raise GitHubPublicationCancelled(
            result(
                GitHubPublicationState.UNKNOWN if child.started else GitHubPublicationState.REFUSED,
                GitHubPublicationFailure.CANCELLED,
            )
        ) from None
    except asyncio.CancelledError:
        raise GitHubPublicationCancelled(
            result(
                GitHubPublicationState.UNKNOWN if child.started else GitHubPublicationState.REFUSED,
                GitHubPublicationFailure.CANCELLED,
            )
        ) from None
    except GitHubCredentialRefused as error:
        facts = error.rate_limit
        return result(
            GitHubPublicationState.REFUSED,
            GitHubPublicationFailure.CREDENTIAL,
            status=facts.status_code if facts else None,
            retry_after=facts.retry_after.total_seconds() if facts else None,
        )
    except (GitHubException, OSError, ValueError, TimeoutError, subprocess.SubprocessError, SQLAlchemyError) as error:
        status = error.response.status_code if isinstance(error, RequestFailed) else None
        retry_after = error.retry_after.total_seconds() if isinstance(error, RateLimitExceeded) else None
        return result(
            GitHubPublicationState.UNKNOWN if child.started else GitHubPublicationState.REFUSED,
            phase,
            status=status,
            retry_after=retry_after,
        )
