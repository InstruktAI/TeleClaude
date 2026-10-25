"""CI run outcomes: translate a project's relayed workflow-run completions into outcome events.

One consumer on each computer is handed the run completions its own computer emitted. The ingress emits every
relayed event, so each completion is translated once in the cluster. A completion becomes a run-completed event
for the project; a green run of a required check on main also announces the revision green once every required
check has a green run for it. Facts the delivery lacks are read from GitHub at completion, so no CI history is
kept. Whether an outcome files a bug is the workflow context's decision, not this one's.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.config.loader import github_actor_for_app_id, load_declared_project_config
from teleclaude.constants import MAIN_BRANCH
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventHomeRef, EventLevel, ReceivedEvent, occurrence_id
from teleclaude.events.producer import EventProducer
from teleclaude.events.references import CiRunRef, CommitRef
from teleclaude.events.schemas.ci import (
    CiCommit,
    CiFailure,
    CiRevisionPassed,
    CiRevisionPassedData,
    CiRunCompleted,
    CiRunCompletedData,
    CiRunLink,
    CiVerdict,
)
from teleclaude.events.type_pattern import TypePattern
from teleclaude.events.wire import LegacyFacts
from teleclaude.github.actions import FAILING_CONCLUSIONS, GitHubActionsReader, RepositoryScope, RunConclusion
from teleclaude.services.project_catalog.service import get_project_catalog_service
from teleclaude.types.github_binding import GitHubActorAssignment

logger = get_logger(__name__)

CI_RUN_OUTCOMES_CONSUMER: Final = "ci-run-outcomes"

_WORKFLOW_RUN_EVENT_TYPE: Final = "github.workflow_run"
_COMPLETED_ACTION: Final = "completed"
_PRODUCER: Final = "integration"
_DOMAIN: Final = "ci"
_RUN_COMPLETED_DESCRIPTION: Final = "CI run {run_id} of {workflow} on {branch} completed: {verdict}"
_REVISION_PASSED_DESCRIPTION: Final = "Revision {revision} passed every required check"
_DECISION_EVENT: Final = "ci_run_outcome_decision"
_APP_UNAVAILABLE_ERROR: Final = "App {app_id} declared by project {project} is not in the GitHub App inventory"
_NO_CONCLUSION_ERROR: Final = "completed run {run_url} states no conclusion"
_RUN_IDENTITY: Final = "{repository_id}/{run_id}/{attempt}"
_COMMIT_IDENTITY: Final = "{repository_id}/{sha}"


class CiAppUnavailable(RuntimeError):
    """The project declares an App the global inventory does not hold, so its runs cannot be read."""


class Decision(StrEnum):
    """What the consumer did with one delivery."""

    PUBLISHED = "published"
    IGNORED = "ignored"


class IgnoreReason(StrEnum):
    """Why a delivery produced no outcome."""

    NO_ORIGIN = "no_origin_project"
    UNREGISTERED_PROJECT = "unregistered_project"
    NOT_COMPLETED = "run_not_completed"
    NO_REPOSITORY = "repository_undeclared"
    NO_APP = "app_undeclared"
    FOREIGN_REPOSITORY = "run_not_in_declared_repository"


class _Repository(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: int


class _WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: int
    name: str
    path: str
    head_branch: str
    head_sha: str
    run_attempt: int
    conclusion: str | None
    html_url: str
    workflow_id: int
    head_repository: _Repository | None


class _WorkflowRunDelivery(BaseModel):
    """The part of GitHub's workflow-run delivery the translation reads."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    action: str
    repository: _Repository
    workflow_run: _WorkflowRun


@dataclass(frozen=True)
class _Declaration:
    """What a project declares for reading and classifying its CI runs."""

    scope: RepositoryScope
    assignment: GitHubActorAssignment
    required_checks: tuple[str, ...]
    update_branch_prefixes: tuple[str, ...]


def _declaration(project_slug: str) -> _Declaration | IgnoreReason:
    """The project's CI declaration, or why it cannot be read: not registered, or no repository or App declared."""
    project = get_project_catalog_service().get_by_slug(project_slug)
    if project is None:
        return IgnoreReason.UNREGISTERED_PROJECT
    config = load_declared_project_config(project.root)
    if config is None or config.todos.repository is None:
        return IgnoreReason.NO_REPOSITORY
    if config.todos.app is None:
        return IgnoreReason.NO_APP
    assignment = github_actor_for_app_id(config.todos.app)
    if assignment is None:
        raise CiAppUnavailable(_APP_UNAVAILABLE_ERROR.format(app_id=config.todos.app, project=project_slug))
    ci = config.ci
    return _Declaration(
        scope=RepositoryScope(repository_id=config.todos.repository.id, repository=config.todos.repository.full_name),
        assignment=assignment,
        required_checks=tuple(ci.required_checks) if ci is not None else (),
        update_branch_prefixes=tuple(ci.dependency_update_branches) if ci is not None else (),
    )


def _verdict(conclusion: str) -> CiVerdict:
    if conclusion in FAILING_CONCLUSIONS:
        return CiVerdict.RED
    if conclusion == RunConclusion.SUCCESS:
        return CiVerdict.GREEN
    return CiVerdict.NONE


@dataclass(frozen=True)
class _FailureFacts:
    """What a red run adds to its outcome: the failures, the last green revision and the commits since it."""

    failures: list[CiFailure]
    last_green_revision: str | None
    commits: list[CiCommit]

    @classmethod
    def none(cls) -> _FailureFacts:
        return cls(failures=[], last_green_revision=None, commits=[])


async def _failure_facts(reader: GitHubActionsReader, run: _WorkflowRun) -> _FailureFacts:
    """Read, at completion, which jobs and steps failed and which commits the failure may come from."""
    failures = [
        CiFailure(job=failed.job, step=failed.step) for failed in await reader.failed_jobs(run.id, run.run_attempt)
    ]
    last_green = await reader.last_green_revision(run.workflow_id, run.head_branch, run.id)
    if last_green is None:
        return _FailureFacts(failures=failures, last_green_revision=None, commits=[])
    commits = [
        CiCommit(sha=commit.sha, subject=commit.subject)
        for commit in await reader.commits_between(last_green, run.head_sha)
    ]
    return _FailureFacts(failures=failures, last_green_revision=last_green, commits=commits)


class _CiRunOutcomes:
    """The handler of one computer's workflow-run completions."""

    def __init__(self, producer: EventProducer) -> None:
        self._producer = producer

    async def handle(self, event: ReceivedEvent) -> None:
        origin = event.home
        if not isinstance(origin, EventHomeRef):
            self._ignored(event, IgnoreReason.NO_ORIGIN)
            return
        delivery = _WorkflowRunDelivery.model_validate(event.data)
        if delivery.action != _COMPLETED_ACTION:
            self._ignored(event, IgnoreReason.NOT_COMPLETED, origin)
            return
        declared = await asyncio.to_thread(_declaration, origin.instance)
        if isinstance(declared, IgnoreReason):
            self._ignored(event, declared, origin)
            return
        run = delivery.workflow_run
        if delivery.repository.id != declared.scope.repository_id:
            self._ignored(event, IgnoreReason.FOREIGN_REPOSITORY, origin)
            return
        await self._publish_outcome(event, origin, declared, run)

    async def _publish_outcome(
        self, event: ReceivedEvent, origin: EventHomeRef, declared: _Declaration, run: _WorkflowRun
    ) -> None:
        if run.conclusion is None:
            raise ValueError(_NO_CONCLUSION_ERROR.format(run_url=run.html_url))
        verdict = _verdict(run.conclusion)
        required = run.path in declared.required_checks
        # A pull request from a fork runs the project's workflows under any branch name its author chooses, and its
        # fork may since have been deleted; only a head in the repository carries the project's branch boundary.
        head_in_repository = run.head_repository is not None and run.head_repository.id == declared.scope.repository_id
        repository_id = declared.scope.repository_id
        reader = GitHubActionsReader(declared.scope, declared.assignment)
        failure = await _failure_facts(reader, run) if verdict is CiVerdict.RED else _FailureFacts.none()
        await self._producer.emit(
            CiRunCompleted(
                id=occurrence_id(CiRunCompleted.type_name(), str(repository_id), str(run.id), str(run.run_attempt)),
                subject=CiRunRef(
                    _RUN_IDENTITY.format(repository_id=repository_id, run_id=run.id, attempt=run.run_attempt)
                ),
                home=origin,
                data=CiRunCompletedData(
                    repository=declared.scope.repository,
                    run_id=run.id,
                    head_in_repository=head_in_repository,
                    workflow=run.name,
                    workflow_path=run.path,
                    required=required,
                    branch=run.head_branch,
                    revision=run.head_sha,
                    run_url=run.html_url,
                    run_attempt=run.run_attempt,
                    conclusion=run.conclusion,
                    verdict=verdict,
                    update_branch=head_in_repository
                    and any(run.head_branch.startswith(prefix) for prefix in declared.update_branch_prefixes),
                    failures=failure.failures,
                    last_green_revision=failure.last_green_revision,
                    commits=failure.commits,
                ),
                causationid=event.id,
            ),
            LegacyFacts(
                producer=_PRODUCER,
                level=EventLevel.WORKFLOW,
                domain=_DOMAIN,
                entity=declared.scope.repository,
                description=_RUN_COMPLETED_DESCRIPTION.format(
                    run_id=run.id, workflow=run.name, branch=run.head_branch, verdict=verdict
                ),
            ),
        )
        logger.info(
            _DECISION_EVENT,
            decision=Decision.PUBLISHED,
            event_id=event.id,
            project=origin.instance,
            type=CiRunCompleted.type_name(),
            run_id=run.id,
            attempt=run.run_attempt,
            workflow_path=run.path,
            verdict=verdict,
            required=required,
        )
        if verdict is CiVerdict.GREEN and required and head_in_repository and run.head_branch == MAIN_BRANCH:
            await self._announce_revision_if_green(event, origin, declared, reader, run)

    async def _announce_revision_if_green(
        self,
        event: ReceivedEvent,
        origin: EventHomeRef,
        declared: _Declaration,
        reader: GitHubActionsReader,
        run: _WorkflowRun,
    ) -> None:
        green_runs = await reader.revision_green(run.head_sha, declared.required_checks, MAIN_BRANCH)
        if green_runs is None:
            return
        await self._producer.emit(
            CiRevisionPassed(
                id=occurrence_id(CiRevisionPassed.type_name(), str(declared.scope.repository_id), run.head_sha),
                subject=CommitRef(
                    _COMMIT_IDENTITY.format(repository_id=declared.scope.repository_id, sha=run.head_sha)
                ),
                home=origin,
                data=CiRevisionPassedData(
                    repository=declared.scope.repository,
                    revision=run.head_sha,
                    runs=[CiRunLink(workflow_path=green.workflow_path, run_url=green.run_url) for green in green_runs],
                ),
                causationid=event.id,
            ),
            LegacyFacts(
                producer=_PRODUCER,
                level=EventLevel.WORKFLOW,
                domain=_DOMAIN,
                entity=declared.scope.repository,
                description=_REVISION_PASSED_DESCRIPTION.format(revision=run.head_sha),
            ),
        )
        logger.info(
            _DECISION_EVENT,
            decision=Decision.PUBLISHED,
            event_id=event.id,
            project=origin.instance,
            type=CiRevisionPassed.type_name(),
            revision=run.head_sha,
        )

    def _ignored(self, event: ReceivedEvent, reason: IgnoreReason, origin: EventHomeRef | None = None) -> None:
        logger.info(
            _DECISION_EVENT,
            decision=Decision.IGNORED,
            event_id=event.id,
            project=origin.instance if origin is not None else None,
            reason=reason,
        )


def build_ci_run_outcomes_consumer(producer: EventProducer) -> Consumer:
    """The consumer that publishes the outcome of each workflow run completed on a project this computer received."""
    return Consumer(
        name=CI_RUN_OUTCOMES_CONSUMER,
        interest=Interest(types=(TypePattern(_WORKFLOW_RUN_EVENT_TYPE),), own_computer_only=True),
        handler=_CiRunOutcomes(producer).handle,
    )
