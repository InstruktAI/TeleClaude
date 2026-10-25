"""CI event declarations: a project's run outcomes and its green main revisions, authored by integration.

Neither type reports a lifecycle state. A run completion is an act about one run and says nothing about the
health of a platform thing, so these events feed no failure correlation and no incident alert.
"""

from __future__ import annotations

from enum import StrEnum

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import CiRunRef, CommitRef

_PROJECT_HOME = (EventHomeKind.PROJECT,)


class CiVerdict(StrEnum):
    """What a run's conclusion says about its revision: it failed, it passed, or it says nothing."""

    RED = "red"
    GREEN = "green"
    NONE = "none"


class CiFailure(EventData):
    """One failed job of a run and the first step of it that failed."""

    job: str
    step: str


class CiCommit(EventData):
    """One commit of the range a failure covers."""

    sha: str
    subject: str


class CiRunLink(EventData):
    """One workflow run, by its workflow file and its address."""

    workflow_path: str
    run_url: str


class CiRunCompletedData(EventData):
    repository: str
    run_id: int
    head_in_repository: bool
    workflow: str
    workflow_path: str
    required: bool
    branch: str
    revision: str
    run_url: str
    run_attempt: int
    conclusion: str
    verdict: CiVerdict
    update_branch: bool
    failures: list[CiFailure]
    last_green_revision: str | None
    commits: list[CiCommit]


class CiRevisionPassedData(EventData):
    repository: str
    revision: str
    runs: list[CiRunLink]


class CiRunCompleted(PlatformEvent[CiRunRef, CiRunCompletedData]):
    NAME = "teleclaude.ci.run.completed"
    DESCRIPTION = "A workflow run completed on a project's repository"
    HOME_KINDS = _PROJECT_HOME
    RELATED_KINDS = ()


class CiRevisionPassed(PlatformEvent[CommitRef, CiRevisionPassedData]):
    NAME = "teleclaude.ci.revision.passed"
    DESCRIPTION = "Every required check has passed on a main revision"
    HOME_KINDS = _PROJECT_HOME
    RELATED_KINDS = ()


DECLARED: tuple[DeclaredEvent, ...] = (
    CiRunCompleted,
    CiRevisionPassed,
)
