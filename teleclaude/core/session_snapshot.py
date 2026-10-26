"""Project stored sessions and their verified issue assignments for viewers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.core.models._snapshot import SessionSnapshot
from teleclaude.core.workflow_store.github_store import read_github_item_issue
from teleclaude.github.issue_lookup import IssueLookupUnavailable, read_issue_reference
from teleclaude.types.github_issue import GitHubIssueReference
from teleclaude.types.work_subject import WorkSubjectParameter

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

_SUBJECT_FIELD = "subject"
_LOOKUP_RETRY_SECONDS = 60
_LOOKUP_CACHE_SIZE = 256
_LOOKUP_UNAVAILABLE_EVENT = "session_github_issue_lookup_unavailable"


@dataclass(frozen=True)
class SessionIssueAssignment:
    """Verified assignment identity used to decide whether enrichment still applies."""

    session_id: str
    command: str
    project_path: str
    selector: str
    subject: str | None

    def applies_to(self, session: Session) -> bool:
        """Reject enrichment resolved for a different source row."""
        return (
            session.session_id == self.session_id
            and session.command == self.command
            and session.project_path == self.project_path
        )


@dataclass(frozen=True)
class SessionIssueMetadata:
    """Optional issue metadata resolved for one assignment."""

    assignment: SessionIssueAssignment
    reference: GitHubIssueReference | None

    def applies_to(self, session: Session) -> bool:
        """Reject enrichment resolved for a different source row."""
        return self.assignment.applies_to(session)


@lru_cache(maxsize=_LOOKUP_CACHE_SIZE)
def _verified_issue(project_path: str, selector: str) -> GitHubIssueReference:
    """Resolve issue identity from the assignment's repository through the GitHub library."""
    return asyncio.run(read_issue_reference(project_path, selector))


@lru_cache(maxsize=_LOOKUP_CACHE_SIZE)
def _issue_lookup_attempt(project_path: str, selector: str, _retry_period: int) -> GitHubIssueReference | None:
    """Cache unavailable lookups for one retry period; verified identities remain cached."""
    try:
        return _verified_issue(project_path, selector)
    except (IssueLookupUnavailable, ValidationError) as error:
        # Issue navigation is optional: a GitHub outage must not make the session view unavailable.
        logger.warning(_LOOKUP_UNAVAILABLE_EVENT, project_path=project_path, error_type=type(error).__name__)
        return None


async def resolve_session_issue_assignment(runtime_db: Db, session: Session) -> SessionIssueAssignment | None:
    """Read the applicable issue assignment without waiting on external metadata."""
    if session.command is None or session.project_path is None:
        return None
    handover = await runtime_db.get_startup_handover(session.session_id)
    invocation = handover.intent.invocation if handover is not None else None
    if invocation is None:
        return None
    parameters = dict(invocation.parameters)
    selector = parameters.get(WorkSubjectParameter.ISSUE)
    if selector is None:
        return None
    subject = parameters.get(WorkSubjectParameter.BRANCH) or parameters.get(WorkSubjectParameter.SLUG)
    return SessionIssueAssignment(
        session_id=session.session_id,
        command=session.command,
        project_path=session.project_path,
        selector=selector,
        subject=subject,
    )


async def resolve_session_issue_metadata(assignment: SessionIssueAssignment) -> SessionIssueMetadata:
    """Resolve optional external issue metadata for an already-read assignment."""
    reference = await asyncio.to_thread(
        _issue_lookup_attempt,
        assignment.project_path,
        assignment.selector,
        int(time.monotonic() / _LOOKUP_RETRY_SECONDS),
    )
    return SessionIssueMetadata(assignment=assignment, reference=reference)


async def resolve_session_work_item_issue(session: Session) -> GitHubIssueReference | None:
    """Read the issue the store recorded for the item this session works, bound to the work slug."""
    if session.project_path is None or session.working_slug is None:
        return None
    reference = await asyncio.to_thread(read_github_item_issue, session.project_path, session.working_slug)
    if reference is None:
        return None
    return reference.model_copy(update={_SUBJECT_FIELD: session.working_slug})


def project_session_snapshot_from_source(
    session: Session,
    *,
    computer: str,
    issue_metadata: SessionIssueMetadata | None = None,
    work_item_issue: GitHubIssueReference | None = None,
) -> SessionSnapshot:
    """Project a current source row with optional metadata already resolved for it.

    The explicit issue reference wins when it applies and is resolved; otherwise the work item's issue applies.
    """
    snapshot = SessionSnapshot.from_db_session(session, computer=computer)
    if issue_metadata is not None and issue_metadata.applies_to(session) and issue_metadata.reference is not None:
        snapshot.github_issue = issue_metadata.reference.model_copy(
            update={_SUBJECT_FIELD: issue_metadata.assignment.subject}
        )
    elif work_item_issue is not None:
        snapshot.github_issue = work_item_issue
    return snapshot


async def project_session_snapshot(runtime_db: Db, session: Session, *, computer: str) -> SessionSnapshot:
    """Build one snapshot with issue identity resolved on the session's owning computer."""
    assignment = await resolve_session_issue_assignment(runtime_db, session)
    if assignment is not None:
        issue_metadata = await resolve_session_issue_metadata(assignment)
        return project_session_snapshot_from_source(session, computer=computer, issue_metadata=issue_metadata)
    work_item_issue = await resolve_session_work_item_issue(session)
    return project_session_snapshot_from_source(session, computer=computer, work_item_issue=work_item_issue)
