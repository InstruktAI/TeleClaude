"""Bring a repository's GitHub board into existence and to its target, from the daemon only.

Only the computer holding the board issue's first claim creates the board; every other computer takes the
board the issue's entries record. The holder first adopts a project the platform App already created with
the repository's name, so an interrupted setup never makes a second board. A refused step is recorded as
the setup's owed cause and the remaining steps still run; the next setup run completes what is owed.
Item writes never call this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.todos_db._github_board import (
    BoardSetup,
    forget_board_items,
    mark_all_board_items_owed_at,
    read_board_setup,
    store_board_setup,
)
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_board_io import (
    GitHubBoardColor,
    GitHubBoardIO,
    GitHubBoardLayout,
    GitHubBoardOption,
)
from teleclaude.core.workflow_store.github_board_record import (
    BOARD_ISSUE_TITLE,
    BoardRecord,
    GitHubBoardRecordRefused,
    lowest_board_issue,
    read_board_record,
    render_board_claim,
    render_board_entry,
    render_board_envelope,
    render_board_issue_body,
)
from teleclaude.core.workflow_store.github_board_reflection import BoardLane
from teleclaude.core.workflow_store.github_io import GitHubWorkflowIO
from teleclaude.core.workflow_store.github_io_models import (
    GitHubBoardOwner,
    GitHubBoardProject,
    GitHubBoardSelectField,
    GitHubBoardState,
    GitHubIssue,
)
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_reflection import IssueState, IssueStateReason
from teleclaude.types.github_binding import GitHubActorAssignment

STATUS_FIELD_NAME = "Status"
NEEDS_YOU_FIELD_NAME = "Needs you"
NEEDS_YOU_OPTION_NAME = "Yes"
_NEEDS_YOU_OPTION_DESCRIPTION = "Waiting on a person; the platform will not move it."
_BOARD_VIEW_NAME = "Board"
_NEEDS_YOU_VIEW_NAME = "Needs you"
_NEEDS_YOU_VIEW_FILTER = "needs-you:Yes"
_BOARD_README_NOTE = (
    "The platform keeps this board true from the project's workflow record. Lanes and the Needs you marker are "
    "written by the platform; a change made by hand here is put back and never steers the work."
)
_BLANK_LINE = "\n\n"
_REPOSITORY_SEPARATOR = "/"
_CAUSE_HELD_ELSEWHERE = "setup is held by computer {}"
_CAUSE_STEP_REFUSED = "{}: {}"
_CAUSE_SEPARATOR = "; "
_CAUSE_MISSING_FIELD = "the project has no {} field"
_SETUP_COMPLETED = "github_store_board_setup_completed"
_SETUP_OWED = "github_store_board_setup_owed"
_SETUP_STEP_REFUSED = "github_store_board_setup_step_refused"
logger = get_logger(__name__)


class BoardSetupCause(StrEnum):
    """Setup causes that are terminal for refresh; only a repair tries them again."""

    PERSONAL_ACCOUNT = "repository owned by a personal account"


class _Step(StrEnum):
    """The steps that bring an existing board to its target, named in the owed cause."""

    README = "readme"
    STATUS_FIELD = "status_field"
    NEEDS_YOU_FIELD = "needs_you_field"
    VIEWS = "views"
    WORKFLOWS = "workflows"
    LINK = "link"


_LANE_STYLE: dict[BoardLane, tuple[GitHubBoardColor, str]] = {
    BoardLane.ICEBOX: (GitHubBoardColor.BLUE, "Parked; not planned for now."),
    BoardLane.PREPARE: (GitHubBoardColor.YELLOW, "Being prepared, up to and including its approvals."),
    BoardLane.WORK: (GitHubBoardColor.ORANGE, "Prepared, being built, reviewed or integrated."),
    BoardLane.DELIVERED: (GitHubBoardColor.GREEN, "Delivered."),
}


@dataclass(frozen=True)
class BoardSetupOutcome:
    """What a setup run leaves owed: its cause, and the computer that holds setup when it is not this one."""

    cause: str | None
    holder: str | None = None


@dataclass(frozen=True)
class BoardRepairOutcome:
    """What a repair could not write: the setup's owed cause and holder, and each item left unwritten with why."""

    setup: BoardSetupOutcome
    unwritten: tuple[tuple[str, str], ...]

    @property
    def complete(self) -> bool:
        """Whether the board now shows everything the record reflects."""
        return self.setup.cause is None and not self.unwritten


@dataclass(frozen=True)
class _Targets:
    """Identities the board's item writes need, learned while bringing the board to its target."""

    status_field_id: str | None
    lane_option_ids: dict[str, str]
    needs_you_field_id: str | None
    needs_you_option_id: str | None
    linked: bool


class GitHubBoardSetup:
    """Run one project's board setup; the caller serializes runs per project."""

    def __init__(
        self,
        db_path: Path,
        repository: GitHubRepositoryIdentity,
        assignment: GitHubActorAssignment,
        issues: GitHubWorkflowIO,
        board: GitHubBoardIO,
        computer: str,
    ) -> None:
        self.db_path = db_path
        self.repository = repository
        self.bot_login = assignment.actor.login
        self.issues = issues
        self.board = board
        self.computer = computer
        owner, _, name = repository.repository.partition(_REPOSITORY_SEPARATOR)
        self._owner_login = owner
        self._title = name

    async def run(self) -> BoardSetupOutcome:
        """Create, adopt or complete the board; never raises for a refusal, which is recorded as owed."""
        setup = read_board_setup(self.db_path)
        try:
            return await self._run(setup)
        except (GitHubIORefused, GitHubBoardRecordRefused) as refused:
            return await self._owed(setup, str(refused))

    async def _run(self, setup: BoardSetup) -> BoardSetupOutcome:
        owner = await self._call(lambda io: io.read_owner())
        if not owner.is_organization:
            return await self._owed(setup, BoardSetupCause.PERSONAL_ACCOUNT.value)
        issue_number = (
            setup.board_issue_number if setup.board_issue_number is not None else await self._board_issue_number()
        )
        setup = replace(setup, board_issue_number=issue_number)
        record = await self._record(issue_number)
        project = await self._recorded_project(record)
        if project is None:
            record = await self._claim_if_unclaimed(issue_number, record)
            if record.holder != self.computer:
                return await self._owed(setup, _CAUSE_HELD_ELSEWHERE.format(record.holder), holder=record.holder)
            project = await self._call(lambda io: io.find_project(owner.owner_id, self._title))
            if project is None:
                project = await self._call(lambda io: io.create_project(owner.owner_id, self._title))
            await self.issues.async_create_comment(issue_number, render_board_entry(project.number))
        return await self._complete(setup, issue_number, project, owner)

    async def _complete(
        self, setup: BoardSetup, issue_number: int, project: GitHubBoardProject, owner: GitHubBoardOwner
    ) -> BoardSetupOutcome:
        if setup.project_id != project.project_id:
            setup = BoardSetup(
                board_issue_number=issue_number, project_number=project.number, project_id=project.project_id
            )
            await asyncio.to_thread(store_board_setup, self.db_path, setup)
            await asyncio.to_thread(forget_board_items, self.db_path)
            await asyncio.to_thread(mark_all_board_items_owed_at, self.db_path)
        state = await self._call(lambda io: io.read_board(project.project_id))
        causes: list[str] = []
        targets = _Targets(
            status_field_id=setup.status_field_id,
            lane_option_ids=dict(setup.lane_option_ids),
            needs_you_field_id=setup.needs_you_field_id,
            needs_you_option_id=setup.needs_you_option_id,
            linked=setup.linked,
        )
        await self._guarded(_Step.README, self._readme(state), causes)
        status = await self._guarded(_Step.STATUS_FIELD, self._status_field(state), causes)
        if status is not None:
            targets = replace(
                targets,
                status_field_id=status.field_id,
                lane_option_ids={name: option_id for option_id, name in status.options},
            )
        needs_you = await self._guarded(_Step.NEEDS_YOU_FIELD, self._needs_you_field(state), causes)
        if needs_you is not None:
            targets = replace(
                targets,
                needs_you_field_id=needs_you.field_id,
                needs_you_option_id=next(
                    (option_id for option_id, name in needs_you.options if name == NEEDS_YOU_OPTION_NAME), None
                ),
            )
        await self._guarded(_Step.VIEWS, self._views(state), causes)
        await self._guarded(_Step.WORKFLOWS, self._workflows(state), causes)
        linked = await self._guarded(_Step.LINK, self._link(state, owner), causes)
        if linked is not None:
            targets = replace(targets, linked=linked)
        cause = _CAUSE_SEPARATOR.join(causes) if causes else None
        await asyncio.to_thread(
            store_board_setup,
            self.db_path,
            BoardSetup(
                board_issue_number=issue_number,
                project_number=project.number,
                project_id=project.project_id,
                status_field_id=targets.status_field_id,
                lane_option_ids=targets.lane_option_ids,
                needs_you_field_id=targets.needs_you_field_id,
                needs_you_option_id=targets.needs_you_option_id,
                linked=targets.linked,
                owed_cause=cause,
            ),
        )
        logger.info(
            _SETUP_COMPLETED if cause is None else _SETUP_OWED,
            project=self.repository.project_path.name,
            project_number=project.number,
            owed=bool(causes),
        )
        return BoardSetupOutcome(cause=cause)

    async def _readme(self, state: GitHubBoardState) -> None:
        target = render_board_envelope(self.repository.repository_id) + _BLANK_LINE + _BOARD_README_NOTE
        if state.readme != target or state.closed:
            await self._call(lambda io: io.set_readme(state.project.project_id, target))

    async def _status_field(self, state: GitHubBoardState) -> GitHubBoardSelectField:
        field = _field_named(state, STATUS_FIELD_NAME)
        if field is None:
            raise GitHubIORefused(
                GitHubIOFailure.VALIDATION_REFUSED, detail=_CAUSE_MISSING_FIELD.format(STATUS_FIELD_NAME)
            )
        lanes = [lane.value for lane in BoardLane]
        if [name for _option_id, name in field.options] == lanes:
            return field
        existing = {name: option_id for option_id, name in field.options}
        options = [
            GitHubBoardOption(
                lane.value, _LANE_STYLE[lane][0], _LANE_STYLE[lane][1], option_id=existing.get(lane.value)
            )
            for lane in BoardLane
        ]
        return await self._call(lambda io: io.set_select_options(field.field_id, options))

    async def _needs_you_field(self, state: GitHubBoardState) -> GitHubBoardSelectField:
        field = _field_named(state, NEEDS_YOU_FIELD_NAME)
        options = [GitHubBoardOption(NEEDS_YOU_OPTION_NAME, GitHubBoardColor.RED, _NEEDS_YOU_OPTION_DESCRIPTION)]
        if field is None:
            return await self._call(
                lambda io: io.create_select_field(state.project.project_id, NEEDS_YOU_FIELD_NAME, options)
            )
        if [name for _option_id, name in field.options] == [NEEDS_YOU_OPTION_NAME]:
            return field
        kept = [
            replace(options[0], option_id=option_id)
            for option_id, name in field.options
            if name == NEEDS_YOU_OPTION_NAME
        ]
        return await self._call(lambda io: io.set_select_options(field.field_id, kept or options))

    async def _views(self, state: GitHubBoardState) -> None:
        views = {view.name: view for view in state.views}
        if _BOARD_VIEW_NAME not in views:
            await self._call(
                lambda io: io.create_view(state.project.project_id, _BOARD_VIEW_NAME, GitHubBoardLayout.BOARD)
            )
        needs_you = views.get(_NEEDS_YOU_VIEW_NAME)
        view_id = (
            needs_you.view_id
            if needs_you is not None
            else await self._call(
                lambda io: io.create_view(state.project.project_id, _NEEDS_YOU_VIEW_NAME, GitHubBoardLayout.TABLE)
            )
        )
        if needs_you is None or needs_you.filter != _NEEDS_YOU_VIEW_FILTER:
            await self._call(lambda io: io.set_view_filter(view_id, _NEEDS_YOU_VIEW_FILTER))

    async def _workflows(self, state: GitHubBoardState) -> None:
        for workflow_id in state.workflow_ids:
            await self._call(partial(GitHubBoardIO.delete_workflow, workflow_id=workflow_id))

    async def _link(self, state: GitHubBoardState, owner: GitHubBoardOwner) -> bool:
        if owner.repository_id not in state.linked_repository_ids:
            await self._call(lambda io: io.link_project(state.project.project_id, owner.repository_id))
        return True

    async def _board_issue_number(self) -> int:
        """Return the lowest-numbered board issue, opening and closing one when the repository has none."""
        repository_id = self.repository.repository_id
        issue = lowest_board_issue(await self.issues.async_list_issues(), self.bot_login, repository_id)
        if issue is None:
            await self._open_board_issue()
            issue = lowest_board_issue(await self.issues.async_list_issues(), self.bot_login, repository_id)
        if issue is None:
            raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED, detail=BOARD_ISSUE_TITLE)
        if not issue.closed:
            await self._close_board_issue(issue)
        return issue.number

    async def _open_board_issue(self) -> None:
        opened = await self.issues.async_open_issue(
            BOARD_ISSUE_TITLE, render_board_issue_body(self.repository.repository_id)
        )
        await self._close_board_issue(opened)

    async def _close_board_issue(self, issue: GitHubIssue) -> None:
        await self.issues.async_update_issue(
            issue.number,
            title=BOARD_ISSUE_TITLE,
            body=render_board_issue_body(self.repository.repository_id),
            state=IssueState.CLOSED.value,
            state_reason=IssueStateReason.NOT_PLANNED.value,
            labels=[],
            issue_type=None,
            assignees=[],
        )

    async def _record(self, issue_number: int) -> BoardRecord:
        comments = await self.issues.async_read_comments(issue_number)
        return read_board_record(comments, self.bot_login, issue_number)

    async def _recorded_project(self, record: BoardRecord) -> GitHubBoardProject | None:
        """Return the board the entries record when GitHub still has it."""
        if record.project_number is None:
            return None
        number = record.project_number
        return await self._call(lambda io: io.find_project_by_number(self._owner_login, number))

    async def _claim_if_unclaimed(self, issue_number: int, record: BoardRecord) -> BoardRecord:
        """Claim setup for this computer when no claim follows the latest entry, then read who holds it."""
        if record.holder is not None:
            return record
        await self.issues.async_create_comment(issue_number, render_board_claim(self.computer))
        return await self._record(issue_number)

    async def _guarded[Result](self, step: _Step, work: Awaitable[Result], causes: list[str]) -> Result | None:
        try:
            return await work
        except GitHubIORefused as refused:
            logger.warning(_SETUP_STEP_REFUSED, step=step.value, reason=refused.reason.value)
            causes.append(_CAUSE_STEP_REFUSED.format(step.value, refused))
            return None

    async def _call[Result](self, work: Callable[[GitHubBoardIO], Awaitable[Result]]) -> Result:
        return await asyncio.wrap_future(self.board.submit(work))

    async def _owed(self, setup: BoardSetup, cause: str, *, holder: str | None = None) -> BoardSetupOutcome:
        await asyncio.to_thread(store_board_setup, self.db_path, replace(setup, owed_cause=cause))
        logger.info(_SETUP_OWED, project=self.repository.project_path.name, reason=cause)
        return BoardSetupOutcome(cause=cause, holder=holder)


def _field_named(state: GitHubBoardState, name: str) -> GitHubBoardSelectField | None:
    return next((field for field in state.fields if field.name == name), None)
