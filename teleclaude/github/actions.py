"""Read GitHub facts about one repository: the Actions facts a run-completion delivery lacks, and the commits and
releases a followed source publishes.

A project's repository is read as the project's App. A followed source this computer holds no App for is read
without a credential, which a public repository allows. The reads are authoritative at the moment they are made,
so the platform holds no CI history. Rate limits and provider failures raise a bounded refusal; nothing is
defaulted, so a consumer retries or dead-letters instead of publishing a guessed fact.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.auth.unauth import UnauthAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit.github import GitHub
from githubkit_schemas.v2026_03_10.models import MinimalRepository
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError

from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.types.github_binding import GitHubActorAssignment

_EMPTY = ""
_REPOSITORY_SEPARATOR = "/"
_PAGE_SIZE = 100
_FIRST_PAGE = 1
_NOT_FOUND_STATUS = 404
_RANGE_TEMPLATE = "{base}...{head}"
_COMMIT_SUBJECT_SEPARATOR = "\n"
_SUCCESSFUL_RUN_FILTER: Final = "success"
_PERMISSIONS: Final[AppPermissionsType] = {"actions": "read", "contents": "read"}
_Client = GitHub[TokenAuthStrategy] | GitHub[UnauthAuthStrategy]
_REFUSAL_WITH_DETAIL = "{reason}: {detail}"
_NO_FAILED_STEP_ERROR = "job {job!r} concluded {conclusion} with no step that did not succeed"
_MISSING_STEPS_ERROR = "job {job!r} of run {run_id} lists no steps"


class RunConclusion(StrEnum):
    """The conclusions GitHub reports for a completed run or job that the platform distinguishes."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMED_OUT = "timed_out"
    STARTUP_FAILURE = "startup_failure"
    SKIPPED = "skipped"
    NEUTRAL = "neutral"


FAILING_CONCLUSIONS: Final = frozenset({RunConclusion.FAILURE, RunConclusion.TIMED_OUT, RunConclusion.STARTUP_FAILURE})
"""Conclusions that mean a run or job failed, as opposed to passed or said nothing about its revision."""

_NOT_FAILED_STEP_CONCLUSIONS: Final = frozenset({RunConclusion.SUCCESS, RunConclusion.SKIPPED, RunConclusion.NEUTRAL})


class GitHubActionsFailure(StrEnum):
    """Bounded reasons a read is refused; none carries provider response text or credential material."""

    CREDENTIAL_REFUSED = "credential_refused"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    UNEXPECTED_SHAPE = "unexpected_shape"


class GitHubActionsRefused(RuntimeError):
    """A read could not be answered; the reason is bounded."""

    def __init__(self, reason: GitHubActionsFailure, detail: str = _EMPTY) -> None:
        super().__init__(_REFUSAL_WITH_DETAIL.format(reason=reason, detail=detail) if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class RepositoryScope:
    """The one repository a reader reads: its stable id and canonical owner/name."""

    repository_id: int
    repository: str


@dataclass(frozen=True)
class PublicRepository:
    """A repository read without a credential: only its canonical owner/name is known."""

    repository: str


@dataclass(frozen=True)
class FailedStep:
    """A failed job and the first of its steps that did not succeed."""

    job: str
    step: str


@dataclass(frozen=True)
class CommitSummary:
    """A commit by sha and the subject line of its message."""

    sha: str
    subject: str


@dataclass(frozen=True)
class GreenRun:
    """A run that concluded success, by its workflow file and its address."""

    workflow_path: str
    run_url: str


@dataclass(frozen=True)
class PublishedRelease:
    """A published release by its tag; drafts and pre-releases are never listed."""

    tag: str


class GitHubActionsReader:
    """Reads facts of one repository: as the App assigned to the project with one installation credential, or,
    for a public repository named without an App, without a credential."""

    def __init__(
        self, scope: RepositoryScope | PublicRepository, assignment: GitHubActorAssignment | None = None
    ) -> None:
        self._repository = scope.repository
        self._scope = scope if isinstance(scope, RepositoryScope) else None
        self._assignment = assignment
        self._owner, _, self._name = scope.repository.partition(_REPOSITORY_SEPARATOR)
        self._token: str | None = None

    async def failed_jobs(self, run_id: int, attempt: int) -> tuple[FailedStep, ...]:
        """The jobs of one run attempt that failed, each with its first step that did not succeed."""

        async def request(client: _Client) -> tuple[FailedStep, ...]:
            failed: list[FailedStep] = []
            page = _FIRST_PAGE
            while True:
                response = await client.rest.actions.async_list_jobs_for_workflow_run_attempt(
                    self._owner, self._name, run_id, attempt, per_page=_PAGE_SIZE, page=page
                )
                jobs = response.parsed_data.jobs
                for job in jobs:
                    if job.conclusion not in FAILING_CONCLUSIONS:
                        continue
                    if not job.steps:
                        raise GitHubActionsRefused(
                            GitHubActionsFailure.UNEXPECTED_SHAPE,
                            _MISSING_STEPS_ERROR.format(job=job.name, run_id=run_id),
                        )
                    step = next((s for s in job.steps if s.conclusion not in _NOT_FAILED_STEP_CONCLUSIONS), None)
                    if step is None:
                        raise GitHubActionsRefused(
                            GitHubActionsFailure.UNEXPECTED_SHAPE,
                            _NO_FAILED_STEP_ERROR.format(job=job.name, conclusion=job.conclusion),
                        )
                    failed.append(FailedStep(job=job.name, step=step.name))
                if len(jobs) < _PAGE_SIZE:
                    return tuple(failed)
                page += 1

        return await self._read(request)

    async def last_green_revision(self, workflow_id: int, branch: str, before_run_id: int) -> str | None:
        """The head sha of the newest successful run of a workflow on a branch older than the given run, or none."""

        async def request(client: _Client) -> str | None:
            page = _FIRST_PAGE
            while True:
                response = await client.rest.actions.async_list_workflow_runs(
                    self._owner,
                    self._name,
                    workflow_id,
                    branch=branch,
                    status=_SUCCESSFUL_RUN_FILTER,
                    per_page=_PAGE_SIZE,
                    page=page,
                )
                runs = response.parsed_data.workflow_runs
                older = [run for run in runs if run.id < before_run_id]
                if older:
                    return max(older, key=lambda run: run.id).head_sha
                if len(runs) < _PAGE_SIZE:
                    return None
                page += 1

        return await self._read(request)

    async def commits_between(self, base: str, head: str) -> tuple[CommitSummary, ...]:
        """The commits after ``base`` up to ``head``, oldest first, as GitHub's comparison returns them."""

        async def request(client: _Client) -> tuple[CommitSummary, ...]:
            response = await client.rest.repos.async_compare_commits(
                self._owner,
                self._name,
                _RANGE_TEMPLATE.format(base=quote(base, safe=_EMPTY), head=quote(head, safe=_EMPTY)),
            )
            return tuple(
                CommitSummary(sha=commit.sha, subject=commit.commit.message.split(_COMMIT_SUBJECT_SEPARATOR, 1)[0])
                for commit in response.parsed_data.commits
            )

        return await self._read(request)

    async def revision_green(
        self, sha: str, workflow_paths: tuple[str, ...], branch: str
    ) -> tuple[GreenRun, ...] | None:
        """The newest run of each named workflow for a revision on a branch of this repository, when every one
        concluded success, else none. Runs on other branches, or whose head is another repository, are not considered."""

        async def request(client: _Client) -> tuple[GreenRun, ...] | None:
            response = await client.rest.actions.async_list_workflow_runs_for_repo(
                self._owner, self._name, head_sha=sha, per_page=_PAGE_SIZE
            )
            newest: dict[str, tuple[int, str, str | None]] = {}
            for run in response.parsed_data.workflow_runs:
                if run.head_branch != branch or not self._head_in_repository(run.head_repository):
                    continue
                known = newest.get(run.path)
                if known is None or run.id > known[0]:
                    newest[run.path] = (run.id, run.html_url, run.conclusion)
            green: list[GreenRun] = []
            for path in workflow_paths:
                latest = newest.get(path)
                if latest is None or latest[2] != RunConclusion.SUCCESS:
                    return None
                green.append(GreenRun(workflow_path=path, run_url=latest[1]))
            return tuple(green)

        return await self._read(request)

    async def recent_commits(self, branch: str, limit: int) -> tuple[str, ...]:
        """The shas of the newest ``limit`` commits of a branch, newest first, in one request."""

        async def request(client: _Client) -> tuple[str, ...]:
            response = await client.rest.repos.async_list_commits(self._owner, self._name, sha=branch, per_page=limit)
            return tuple(commit.sha for commit in response.parsed_data)

        return await self._read(request)

    async def published_releases(self) -> tuple[PublishedRelease, ...]:
        """Every published release, following the provider's pages until none remains.

        The provider orders releases by creation, not by version, so no earlier cutoff is complete.
        """

        async def request(client: _Client) -> tuple[PublishedRelease, ...]:
            published: list[PublishedRelease] = []
            page = _FIRST_PAGE
            while True:
                response = await client.rest.repos.async_list_releases(
                    self._owner, self._name, per_page=_PAGE_SIZE, page=page
                )
                releases = response.parsed_data
                published.extend(
                    PublishedRelease(tag=release.tag_name)
                    for release in releases
                    if not release.draft and not release.prerelease
                )
                if len(releases) < _PAGE_SIZE:
                    return tuple(published)
                page += 1

        return await self._read(request)

    def _head_in_repository(self, head_repository: MinimalRepository) -> bool:
        """Whether a run's head is this repository: by stable id when it is known, else by canonical name."""
        if self._scope is not None:
            return head_repository.id == self._scope.repository_id
        return head_repository.full_name == self._repository

    async def _read[ResultT](self, request: Callable[[_Client], Awaitable[ResultT]]) -> ResultT:
        try:
            if self._scope is None or self._assignment is None:
                async with create_github_client(UnauthAuthStrategy(), MemCacheStrategy()) as public_client:
                    return await request(public_client)
            if self._token is None:
                credential = await issue_github_installation_credential(self._assignment, self._scope, _PERMISSIONS)
                self._token = credential.token.get_secret_value()
            async with create_github_client(TokenAuthStrategy(self._token), MemCacheStrategy()) as client:
                return await request(client)
        except GitHubCredentialRefused:
            raise GitHubActionsRefused(GitHubActionsFailure.CREDENTIAL_REFUSED) from None
        except RateLimitExceeded:
            raise GitHubActionsRefused(GitHubActionsFailure.RATE_LIMITED) from None
        except RequestFailed as error:
            if error.response.status_code == _NOT_FOUND_STATUS:
                raise GitHubActionsRefused(GitHubActionsFailure.NOT_FOUND) from None
            raise GitHubActionsRefused(GitHubActionsFailure.UNAVAILABLE) from None
        except (GitHubException, HTTPError, TimeoutError, OSError):
            raise GitHubActionsRefused(GitHubActionsFailure.UNAVAILABLE) from None
