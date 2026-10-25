"""Failed-check bugs: file a bug for each failure of a required CI check, add repeats to it, record recoveries on it.

One consumer on each computer is handed the run-completed outcomes its own computer emitted, so each run is filed
once in the cluster, in the store of the project it belongs to. A red outcome of a required check on main or on a
dependency update files one bug per failed job and step, identified by a fingerprint. A failure whose fingerprint has
an open bug is added to that bug; a green outcome of the same check is recorded on every open bug that holds an
unrecovered failure on its branch. No agent is involved: the bug enters the ordinary bug lane, which diagnoses it.

Every step resumes from what exists, so handling an outcome again after any interruption completes the filing
without a second bug.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_CHECK_FAILURES,
    ARTIFACT_INPUT,
    MAIN_BRANCH,
    SYSTEM_DAEMON_PRINCIPAL,
)
from teleclaude.core.next_machine.check_failures import (
    AnnouncedEntry,
    CheckFailures,
    CommitEntry,
    FailureEntry,
    RecoveryEntry,
    fingerprint_line,
    fingerprint_of,
)
from teleclaude.core.next_machine.state_io import initial_todo_state_for_kind
from teleclaude.core.next_machine.todo_creation import NewTodo, announce_todo_created, write_new_todo
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import WorkItem
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventHomeRef, ReceivedEvent, occurrence_id
from teleclaude.events.schemas.ci import CiFailure, CiRunCompleted, CiRunCompletedData, CiVerdict
from teleclaude.events.schemas.sdlc import TodoCreated
from teleclaude.events.type_pattern import TypePattern
from teleclaude.services.project_catalog.service import get_project_catalog_service
from teleclaude.slug import normalize_slug
from teleclaude.types.creation_record import EntryPoint, Lineage
from teleclaude.types.todo_kind import TodoKind

logger = get_logger(__name__)

FAILED_CHECK_BUGS_CONSUMER: Final = "failed-check-bugs"

_DECISION_EVENT: Final = "failed_check_bug_decision"
_SLUG_PREFIX: Final = "ci"
_SLUG_PART_SEPARATOR: Final = "-"
_SLUG_MAX_LENGTH: Final = 60
_FIRST_DISAMBIGUATOR: Final = 2
_NEWLINE: Final = "\n"
_CREATED_BUG_NOT_FOUND_ERROR: Final = "the bug filed for fingerprint {fingerprint} is not among the open bugs"
_INPUT_TITLE: Final = "# {slug} — Input\n\n{body}\n"
_INPUT_BODY: Final = (
    "The required check `{workflow_path}` failed at job `{job}`, step `{step}`.\n\n"
    "{fingerprint_line}\n\n"
    "The contract this breaks: the project declares `{workflow_path}` a required check, so a revision on main or on "
    "a dependency update passes it.\n\n"
    "- Revision: {revision}\n"
    "- Branch: {branch}\n"
    "- Run: {run_url} (attempt {attempt})\n\n"
    "{commit_range}\n\n"
    "The cause is not established. Which change or component is at fault, and whether the check itself is wrong, is "
    "for the bug lane to diagnose. The occurrences and recoveries of this failure are recorded in the "
    "`check-failures` artifact."
)
_COMMIT_RANGE_SINCE_GREEN: Final = "Commits since this branch's last green run of the check ({last_green}):\n{commits}"
_COMMIT_RANGE_NO_GREEN: Final = "This branch has no earlier green run of the check, so no commit range is stated."
_COMMIT_LINE: Final = "- {sha} {subject}"
_NO_COMMITS: Final = "- (none)"


class Decision(StrEnum):
    """What the filer did with one failure or recovery."""

    FILED = "filed"
    APPENDED = "appended"
    ALREADY_RECORDED = "already_recorded"
    RECOVERED = "recovered"
    IGNORED = "ignored"


class IgnoreReason(StrEnum):
    """Why an outcome files nothing and records nothing."""

    NO_ORIGIN = "no_origin_project"
    UNREGISTERED_PROJECT = "unregistered_project"
    NOT_REQUIRED = "not_a_required_check"
    NO_VERDICT = "run_says_nothing_about_its_revision"
    HEAD_OUTSIDE_REPOSITORY = "run_head_is_outside_the_repository"
    INELIGIBLE_BRANCH = "branch_is_neither_main_nor_a_dependency_update"
    NO_FAILURE_IDENTIFIED = "red_run_names_no_failed_job"


def _bug_slug(workflow_path: str, failure: CiFailure, disambiguator: int | None) -> str:
    """The bug's name: the check, job and step, normalized and bounded; a number follows when the name is taken."""
    stem = PurePosixPath(workflow_path).stem
    base = normalize_slug(_SLUG_PART_SEPARATOR.join((_SLUG_PREFIX, stem, failure.job, failure.step)))
    suffix = _SLUG_PART_SEPARATOR + str(disambiguator) if disambiguator is not None else ""
    return base[: _SLUG_MAX_LENGTH - len(suffix)].rstrip(_SLUG_PART_SEPARATOR) + suffix


def _bug_input(slug: str, data: CiRunCompletedData, failure: CiFailure, fingerprint: str) -> str:
    """The bug's input: what failed, the contract it breaks, and the evidence of this occurrence."""
    if data.last_green_revision is None:
        commit_range = _COMMIT_RANGE_NO_GREEN
    else:
        commits = _NEWLINE.join(_COMMIT_LINE.format(sha=commit.sha, subject=commit.subject) for commit in data.commits)
        commit_range = _COMMIT_RANGE_SINCE_GREEN.format(
            last_green=data.last_green_revision, commits=commits or _NO_COMMITS
        )
    body = _INPUT_BODY.format(
        workflow_path=data.workflow_path,
        job=failure.job,
        step=failure.step,
        fingerprint_line=fingerprint_line(fingerprint),
        revision=data.revision,
        branch=data.branch,
        run_url=data.run_url,
        attempt=data.run_attempt,
        commit_range=commit_range,
    )
    return _INPUT_TITLE.format(slug=slug, body=body)


async def _open_platform_bugs(store: WorkflowStore) -> list[WorkItem]:
    """The bugs the platform filed that are neither delivered nor removed."""
    items = await store.list_todo(include_icebox=True)
    return [item for item in items if item["entry_point"] == EntryPoint.PLATFORM.value]


async def _open_bug_of(store: WorkflowStore, fingerprint: str) -> WorkItem | None:
    """The open bug that carries the fingerprint: by its record, or by its input when the record was never written."""
    for bug in await _open_platform_bugs(store):
        slug = bug["slug"]
        record_text = await store.read_artifact(slug, ARTIFACT_CHECK_FAILURES)
        if record_text:
            if CheckFailures.parse(record_text).fingerprint == fingerprint:
                return bug
            continue
        input_text = await store.read_artifact(slug, ARTIFACT_INPUT)
        if fingerprint_line(fingerprint) in input_text.split(_NEWLINE):
            return bug
    return None


class _FailedCheckBugs:
    """The handler of one computer's run-completed outcomes."""

    async def handle(self, event: ReceivedEvent) -> None:
        origin = event.home
        if not isinstance(origin, EventHomeRef):
            self._ignored(event, IgnoreReason.NO_ORIGIN, None)
            return
        data = CiRunCompletedData.model_validate(event.data)
        if not data.required:
            self._ignored(event, IgnoreReason.NOT_REQUIRED, origin)
            return
        if data.verdict is CiVerdict.NONE:
            self._ignored(event, IgnoreReason.NO_VERDICT, origin)
            return
        if not data.head_in_repository:
            self._ignored(event, IgnoreReason.HEAD_OUTSIDE_REPOSITORY, origin)
            return
        project = get_project_catalog_service().get_by_slug(origin.instance)
        if project is None:
            self._ignored(event, IgnoreReason.UNREGISTERED_PROJECT, origin)
            return
        store = await get_workflow_store(project.root)
        if data.verdict is CiVerdict.GREEN:
            await self._record_recoveries(store, event, origin, data)
            return
        if data.branch != MAIN_BRANCH and not data.update_branch:
            self._ignored(event, IgnoreReason.INELIGIBLE_BRANCH, origin)
            return
        if not data.failures:
            self._ignored(event, IgnoreReason.NO_FAILURE_IDENTIFIED, origin)
            return
        for failure in data.failures:
            await self._file_failure(store, str(project.root), event, origin, data, failure)

    async def _file_failure(
        self,
        store: WorkflowStore,
        project_root: str,
        event: ReceivedEvent,
        origin: EventHomeRef,
        data: CiRunCompletedData,
        failure: CiFailure,
    ) -> None:
        fingerprint = fingerprint_of(data.workflow_path, failure.job, failure.step)
        bug = await _open_bug_of(store, fingerprint)
        filed = bug is None
        if bug is None:
            await self._create_bug(store, project_root, data, failure, fingerprint)
            bug = await _open_bug_of(store, fingerprint)
            if bug is None:
                raise RuntimeError(_CREATED_BUG_NOT_FOUND_ERROR.format(fingerprint=fingerprint))
        slug = bug["slug"]
        new = self._new_bug(project_root, slug, _bug_input(slug, data, failure, fingerprint))
        record_text = await store.read_artifact(slug, ARTIFACT_CHECK_FAILURES)
        record = (
            CheckFailures.parse(record_text)
            if record_text
            else CheckFailures.start(data.workflow_path, failure.job, failure.step)
        )
        appended = not record.holds_failure(data.run_id, data.run_attempt, failure.job)
        if appended:
            record = record.append(self._failure_entry(data, failure))
        if appended or not record_text:
            await store.write_artifact(slug, ARTIFACT_CHECK_FAILURES, record.render())
        if not record.announced:
            await announce_todo_created(
                new,
                identity=slug,
                lifecycle_phase=str(new.state["lifecycle_phase"]),
                pickup_requested=True,
                event_id=occurrence_id(TodoCreated.type_name(), origin.instance, bug["id"]),
            )
            record = record.append(AnnouncedEntry())
            await store.write_artifact(slug, ARTIFACT_CHECK_FAILURES, record.render())
        decision = Decision.FILED if filed else Decision.APPENDED if appended else Decision.ALREADY_RECORDED
        logger.info(
            _DECISION_EVENT,
            decision=decision,
            event_id=event.id,
            project=origin.instance,
            slug=slug,
            fingerprint=fingerprint,
            workflow_path=data.workflow_path,
            job=failure.job,
            step=failure.step,
            run_url=data.run_url,
        )

    async def _create_bug(
        self, store: WorkflowStore, project_root: str, data: CiRunCompletedData, failure: CiFailure, fingerprint: str
    ) -> None:
        """Create the bug under the next free name, its input stating the fingerprint in the creation itself."""
        disambiguator: int | None = None
        slug = _bug_slug(data.workflow_path, failure, disambiguator)
        while await store.find_live_slug_conflict(slug) is not None:
            disambiguator = _FIRST_DISAMBIGUATOR if disambiguator is None else disambiguator + 1
            slug = _bug_slug(data.workflow_path, failure, disambiguator)
        await write_new_todo(store, self._new_bug(project_root, slug, _bug_input(slug, data, failure, fingerprint)))

    def _new_bug(self, project_root: str, slug: str, input_body: str) -> NewTodo:
        """The creation of a failed-check bug: the platform's door, under the system principal, with no human."""
        return NewTodo(
            slug=slug,
            kind=TodoKind.BUG,
            state=initial_todo_state_for_kind(TodoKind.BUG),
            lineage=Lineage.create(root=SYSTEM_DAEMON_PRINCIPAL),
            entry_point=EntryPoint.PLATFORM,
            human_involved=False,
            cwd=project_root,
            artifact_name=ARTIFACT_INPUT,
            artifact_body=input_body,
            session_id=None,
        )

    def _failure_entry(self, data: CiRunCompletedData, failure: CiFailure) -> FailureEntry:
        return FailureEntry(
            run_id=data.run_id,
            run_url=data.run_url,
            attempt=data.run_attempt,
            job=failure.job,
            branch=data.branch,
            revision=data.revision,
            last_green_revision=data.last_green_revision,
            commits=[CommitEntry(sha=commit.sha, subject=commit.subject) for commit in data.commits],
        )

    async def _record_recoveries(
        self, store: WorkflowStore, event: ReceivedEvent, origin: EventHomeRef, data: CiRunCompletedData
    ) -> None:
        """Record the green run on every open bug that holds an unrecovered failure of this check on this branch."""
        for bug in await _open_platform_bugs(store):
            slug = bug["slug"]
            record_text = await store.read_artifact(slug, ARTIFACT_CHECK_FAILURES)
            if not record_text:
                continue
            record = CheckFailures.parse(record_text)
            if record.workflow_path != data.workflow_path or not record.recovery_due(
                data.branch, data.run_id, data.run_attempt
            ):
                continue
            recovered = record.append(
                RecoveryEntry(
                    run_id=data.run_id,
                    run_url=data.run_url,
                    attempt=data.run_attempt,
                    branch=data.branch,
                    revision=data.revision,
                )
            )
            await store.write_artifact(slug, ARTIFACT_CHECK_FAILURES, recovered.render())
            logger.info(
                _DECISION_EVENT,
                decision=Decision.RECOVERED,
                event_id=event.id,
                project=origin.instance,
                slug=slug,
                fingerprint=record.fingerprint,
                workflow_path=data.workflow_path,
                branch=data.branch,
                run_url=data.run_url,
            )

    def _ignored(self, event: ReceivedEvent, reason: IgnoreReason, origin: EventHomeRef | None) -> None:
        logger.info(
            _DECISION_EVENT,
            decision=Decision.IGNORED,
            event_id=event.id,
            project=origin.instance if origin is not None else None,
            reason=reason,
        )


def build_failed_check_bugs_consumer() -> Consumer:
    """The consumer that files, extends and settles failed-check bugs for the outcomes this computer emitted."""
    return Consumer(
        name=FAILED_CHECK_BUGS_CONSUMER,
        interest=Interest(types=(TypePattern(CiRunCompleted.type_name()),), own_computer_only=True),
        handler=_FailedCheckBugs().handle,
    )
