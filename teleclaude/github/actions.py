"""Read GitHub Actions facts a run-completion delivery lacks, as the project's App on one repository.

The reads are authoritative at the moment they are made, so the platform holds no CI history. Rate limits and
provider failures raise a bounded refusal; nothing is defaulted, so a consumer retries or dead-letters instead
of publishing a guessed fact.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit.github import GitHub
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


class GitHubActionsReader:
    """Reads Actions facts of one repository as the App assigned to the project, with one installation credential."""

    def __init__(self, scope: RepositoryScope, assignment: GitHubActorAssignment) -> None:
        self._scope = scope
        self._assignment = assignment
        self._owner, _, self._name = scope.repository.partition(_REPOSITORY_SEPARATOR)
        self._token: str | None = None

    async def failed_jobs(self, run_id: int, attempt: int) -> tuple[FailedStep, ...]:
        """The jobs of one run attempt that failed, each with its first step that did not succeed."""

        async def request(client: GitHub[TokenAuthStrategy]) -> tuple[FailedStep, ...]:
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

        async def request(client: GitHub[TokenAuthStrategy]) -> str | None:
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

        async def request(client: GitHub[TokenAuthStrategy]) -> tuple[CommitSummary, ...]:
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

        async def request(client: GitHub[TokenAuthStrategy]) -> tuple[GreenRun, ...] | None:
            response = await client.rest.actions.async_list_workflow_runs_for_repo(
                self._owner, self._name, head_sha=sha, per_page=_PAGE_SIZE
            )
            newest: dict[str, tuple[int, str, str | None]] = {}
            for run in response.parsed_data.workflow_runs:
                if run.head_branch != branch or run.head_repository.id != self._scope.repository_id:
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

    async def _read[ResultT](self, request: Callable[[GitHub[TokenAuthStrategy]], Awaitable[ResultT]]) -> ResultT:
        try:
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
