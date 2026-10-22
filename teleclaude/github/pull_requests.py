"""Maintain a creating builder's recorded PR description through the finite native executor."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.models import PullRequest
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.db import get_db
from teleclaude.core.github_identity import (
    GitHubPostingContext,
    ManagedGitHubInvocation,
    resolve_github_builder_parent,
    resolve_native_github_posting_context,
)
from teleclaude.core.roles import RoleName
from teleclaude.github import _native_gh
from teleclaude.github._pr_provider import pr_reader, pr_reference, prose_digest, verify_pr
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.types.github_binding import GitHubSessionBinding
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubEditEvidence,
    GitHubObjectAssociation,
    GitHubObjectRef,
    GitHubPullRequestDescriptionMutation,
    NativeGitHubPostSource,
)
from teleclaude.types.github_publication import (
    GitHubPullRequestEditRequest,
    GitHubPullRequestFailure,
    GitHubPullRequestResult,
    GitHubPullRequestSnapshot,
    GitHubPullRequestStage,
    GitHubPushProof,
)

_HEADS = "refs/heads/"
_MAIN = "main"
_EMPTY = ""
_UTF8 = "utf-8"
_TITLE = "title"
_BODY = "body"
_PATCH_ENDPOINT = "repos/{repository}/pulls/{number}"
_CONFIG_PREFIX = "teleclaude-gh-pr-"
_GH_CONFIG_DIR = "GH_CONFIG_DIR"
_GH_TOKEN = "GH_TOKEN"
_FIXED_ENVIRONMENT = {"GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "GH_PAGER": ""}
_PR_PERMISSIONS: AppPermissionsType = {"pull_requests": "write", "contents": "read"}
_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_CANCELLED = "PR description maintenance cancelled; known provider effects are attached"


@dataclass(frozen=True)
class _BuilderFacts:
    parent: GitHubSessionBinding
    proofs: tuple[GitHubPushProof, ...]


class GitHubPullRequestCancelled(asyncio.CancelledError):
    """Preserve cancellation and safe known object/effect facts, without retry or association inference."""

    def __init__(self, result: GitHubPullRequestResult) -> None:
        super().__init__(_CANCELLED)
        self.result = result


async def _builder_facts(context: GitHubPostingContext) -> _BuilderFacts | GitHubPullRequestFailure:
    if not isinstance(context.invocation, ManagedGitHubInvocation) or context.binding.role is not RoleName.BUILDER:
        return GitHubPullRequestFailure.BUILDER
    target = context.target
    if not target.branch or not target.base or target.branch == target.base or target.branch == _MAIN:
        return GitHubPullRequestFailure.WORK_REF
    if await resolve_native_github_posting_context() != context:
        return GitHubPullRequestFailure.CONTEXT
    parent = await resolve_github_builder_parent(context)
    if not isinstance(parent, GitHubSessionBinding):
        return GitHubPullRequestFailure.PARENT
    try:
        store = await get_db()
        proofs = tuple(
            proof
            for proof in await store.get_github_push_proofs(context.binding.session_id)
            if (
                proof.binding == context.binding
                and proof.target == context.target
                and proof.ref == _HEADS + target.branch
                and proof.before != proof.after
            )
        )
    except (SQLAlchemyError, OSError, ValueError):
        return GitHubPullRequestFailure.PROOF
    if not proofs:
        return GitHubPullRequestFailure.PROOF
    return _BuilderFacts(parent, proofs)


async def _read_creator(ref: GitHubObjectRef) -> GitHubObjectAssociation | None:
    """Missing or unreadable immutable provenance establishes no maintenance owner."""
    try:
        store = await get_db()
        return await store.get_github_object_association(ref)
    except (SQLAlchemyError, OSError, ValueError):
        return None


def _description_payload(request: GitHubPullRequestEditRequest) -> bytes:
    """Only explicitly requested description fields can reach the fixed PATCH."""
    payload: dict[str, str] = {}
    if request.title is not None:
        payload[_TITLE] = request.title
    if request.body is not None:
        payload[_BODY] = request.body
    return json.dumps(payload, ensure_ascii=False).encode(_UTF8)


def _sdk_response(error: Exception) -> _native_gh.Response | None:
    """Translate only safe provider status/delay, never raw request or response diagnostics."""
    if isinstance(error, RateLimitExceeded):
        return _native_gh.Response(error.response.status_code, retry_after=error.retry_after, started=False)
    if isinstance(error, RequestFailed):
        return _native_gh.Response(error.response.status_code, started=False)
    return None


def _creator_matches(
    creation: GitHubObjectAssociation | None,
    context: GitHubPostingContext,
    snapshot: GitHubPullRequestSnapshot,
) -> bool:
    return (
        creation is not None
        and creation.object == snapshot.object
        and isinstance(creation.source, NativeGitHubPostSource)
        and creation.session_id == context.binding.session_id
        and creation.role is RoleName.BUILDER
        and creation.work_issue_number == context.target.issue_number
        and creation.actor.same_account(context.binding.assignment.actor)
        and creation.pull_request is not None
        and creation.pull_request.head_ref == context.target.branch
        and creation.pull_request.base_ref == context.target.base
    )


def _edit_response(
    response: _native_gh.Response,
    context: GitHubPostingContext,
    request: GitHubPullRequestEditRequest,
    before: PullRequest,
    ref: GitHubObjectRef,
    head: str,
) -> tuple[GitHubAcceptance, GitHubObjectRef, GitHubPullRequestSnapshot | None, GitHubPullRequestFailure | None]:
    if response.status != 200:
        definite = not response.started or response.status in _REJECTIONS
        return (
            GitHubAcceptance.NO_EFFECT if definite else GitHubAcceptance.UNKNOWN,
            ref,
            None,
            GitHubPullRequestFailure.REFUSED if definite else GitHubPullRequestFailure.UNKNOWN,
        )
    observed = ref
    try:
        data = PullRequest.model_validate_json(response.body)
        observed = pr_reference(data, context)
        snapshot = verify_pr(data, context, head)
        title = request.title if request.title is not None else before.title
        body = request.body if request.body is not None else (before.body if before.body is not None else _EMPTY)
        if (
            observed != ref
            or snapshot.title_digest != prose_digest(title)
            or snapshot.body_digest != prose_digest(body)
        ):
            return GitHubAcceptance.CONFIRMED, observed, snapshot, GitHubPullRequestFailure.PROVIDER
        return GitHubAcceptance.CONFIRMED, observed, snapshot, None
    except ValueError:
        return GitHubAcceptance.CONFIRMED, observed, None, GitHubPullRequestFailure.PROVIDER


async def edit_native_pull_request(
    context: GitHubPostingContext,
    request: GitHubPullRequestEditRequest,
) -> GitHubPullRequestResult:
    """Edit only explicit title/body of this builder's recorded PR, with separate later attribution."""
    stage = GitHubPullRequestStage.ADMISSION
    acceptance = GitHubAcceptance.NO_EFFECT
    ref: GitHubObjectRef | None = None
    snapshot: GitHubPullRequestSnapshot | None = None
    creation: GitHubObjectAssociation | None = None
    mutation: GitHubPullRequestDescriptionMutation | None = None
    response: _native_gh.Response | None = None
    credential_refusal: str | None = None

    def result(failure: GitHubPullRequestFailure | None = None) -> GitHubPullRequestResult:
        return GitHubPullRequestResult(
            operation=request.operation,
            stage=stage,
            acceptance=acceptance,
            failure=failure,
            object=ref,
            snapshot=snapshot,
            association=creation,
            mutation=mutation,
            provider_status=response.status if response else None,
            retry_after=response.retry_after if response else None,
            credential_refusal=credential_refusal,
        )

    try:
        facts = await _builder_facts(context)
        if isinstance(facts, GitHubPullRequestFailure):
            return result(facts)
        if request.target != context.target:
            return result(GitHubPullRequestFailure.CONTEXT)
        encoded = _description_payload(request)
        environment = _native_gh.launch_environment()
        binary = _native_gh.gh_binary(environment)
        if binary is None:
            return result(GitHubPullRequestFailure.CREDENTIAL)
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as temporary:
            # Protected key lookup remains after current authoritative admission and prose collection.
            if await _builder_facts(context) != facts:
                return result(GitHubPullRequestFailure.CONTEXT)
            credential = await issue_github_installation_credential(
                context.binding.assignment, context.target, _PR_PERMISSIONS
            )
            environment.update(
                {**_FIXED_ENVIRONMENT, _GH_CONFIG_DIR: temporary, _GH_TOKEN: credential.token.get_secret_value()}
            )
            async with pr_reader(credential) as (reader, client):
                stage = GitHubPullRequestStage.DISCOVERY
                discovery = await reader.discover(client)
                if request.number not in discovery.numbers:
                    return result(GitHubPullRequestFailure.DISCOVERY)
                stage = GitHubPullRequestStage.PREFLIGHT
                head = discovery.head
                proof = next((proof for proof in facts.proofs if proof.after == head), None)
                if proof is None:
                    return result(GitHubPullRequestFailure.PROOF)
                before = await reader.get(client, request.number)
                ref = pr_reference(before, context)
                snapshot = verify_pr(before, context, proof.after)
                creation = await _read_creator(ref)
                if not _creator_matches(creation, context, snapshot):
                    return result(GitHubPullRequestFailure.CREATOR)
                # Repeat authoritative facts and exact creator/head reads before the only mutation.
                fresh = await _builder_facts(context)
                if isinstance(fresh, GitHubPullRequestFailure):
                    return result(fresh)
                if (
                    fresh.parent != facts.parent
                    or proof not in fresh.proofs
                    or await reader.head(client) != proof.after
                ):
                    return result(GitHubPullRequestFailure.PROOF)
                current_creation = await _read_creator(ref)
                if current_creation is None or creation is None or not current_creation.same_creation(creation):
                    return result(GitHubPullRequestFailure.CREATOR)
                before = await reader.get(client, request.number)
                snapshot = verify_pr(before, context, proof.after)
                if snapshot.object != ref:
                    return result(GitHubPullRequestFailure.PROVIDER)
                before_snapshot = snapshot
                stage = GitHubPullRequestStage.MUTATION
                try:
                    response = await _native_gh.send(
                        binary,
                        _PATCH_ENDPOINT.format(repository=context.target.repository, number=request.number),
                        encoded,
                        environment,
                        temporary,
                        method=_native_gh.CommentMethod.PATCH,
                    )
                except _native_gh.SendCancelled as error:
                    response = error.response
                    acceptance, ref, snapshot, _ = _edit_response(response, context, request, before, ref, proof.after)
                    raise GitHubPullRequestCancelled(result(GitHubPullRequestFailure.CANCELLED)) from None
                acceptance, ref, snapshot, failure = _edit_response(
                    response, context, request, before, ref, proof.after
                )
                if failure is not None or snapshot is None:
                    return result(failure or GitHubPullRequestFailure.PROVIDER)
                stage = GitHubPullRequestStage.ATTRIBUTION
                fresh = await _builder_facts(context)
                if (
                    isinstance(fresh, GitHubPullRequestFailure)
                    or fresh.parent != facts.parent
                    or proof not in fresh.proofs
                ):
                    return result(GitHubPullRequestFailure.RETENTION)
                candidate = GitHubPullRequestDescriptionMutation(
                    object=ref,
                    session_id=context.binding.session_id,
                    role=context.binding.role,
                    actor=context.binding.assignment.actor,
                    observed_at=datetime.now(UTC),
                    head_sha=snapshot.head_sha,
                    title_digest=snapshot.title_digest,
                    body_digest=snapshot.body_digest,
                    before_title_digest=before_snapshot.title_digest,
                    before_body_digest=before_snapshot.body_digest,
                    edit_evidence=GitHubEditEvidence(updated_at=snapshot.updated_at),
                )
                store = await get_db()
                mutation = await store.record_github_pr_description(
                    candidate, creation=creation, proof=proof, parent=facts.parent
                )
                return result()
    except GitHubPullRequestCancelled:
        raise
    except asyncio.CancelledError:
        raise GitHubPullRequestCancelled(result(GitHubPullRequestFailure.CANCELLED)) from None
    except GitHubCredentialRefused as error:
        credential_refusal = error.reason.value
        rate_limit = error.rate_limit
        response = _native_gh.Response(
            rate_limit.status_code if rate_limit else None,
            retry_after=rate_limit.retry_after if rate_limit else None,
            started=False,
        )
        return result(GitHubPullRequestFailure.CREDENTIAL)
    except (GitHubException, OSError, ValueError, TimeoutError, SQLAlchemyError) as error:
        response = _sdk_response(error) or response
        failure = (
            GitHubPullRequestFailure.RETENTION
            if stage is GitHubPullRequestStage.ATTRIBUTION
            else (
                GitHubPullRequestFailure.DISCOVERY
                if stage is GitHubPullRequestStage.DISCOVERY
                else GitHubPullRequestFailure.PROVIDER
            )
        )
        return result(failure)
