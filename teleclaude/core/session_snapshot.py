"""Project stored sessions and their verified issue assignments for viewers."""

from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.core.models._snapshot import SessionSnapshot
from teleclaude.types.github_issue import GitHubIssueReference
from teleclaude.types.work_subject import WorkSubjectParameter

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

_SUBJECT_FIELD = "subject"
_GH_ISSUE_VIEW = ("gh", "issue", "view", "--json", "number,url", "--")
_LOOKUP_TIMEOUT_SECONDS = 10
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
    """Resolve issue identity using the assignment's own GitHub repository selection."""
    # GitHub CLI owns the assignment's authenticated repository selection; no Python API reproduces it.
    result = subprocess.run(
        [*_GH_ISSUE_VIEW, selector],
        cwd=project_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=_LOOKUP_TIMEOUT_SECONDS,
    )
    return GitHubIssueReference.model_validate_json(result.stdout)


@lru_cache(maxsize=_LOOKUP_CACHE_SIZE)
def _issue_lookup_attempt(project_path: str, selector: str, _retry_period: int) -> GitHubIssueReference | None:
    """Cache unavailable lookups for one retry period; verified identities remain cached."""
    try:
        return _verified_issue(project_path, selector)
    except (OSError, subprocess.SubprocessError, ValidationError) as error:
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


def project_session_snapshot_from_source(
    session: Session,
    *,
    computer: str,
    issue_metadata: SessionIssueMetadata | None = None,
) -> SessionSnapshot:
    """Project a current source row with optional metadata already resolved for it."""
    snapshot = SessionSnapshot.from_db_session(session, computer=computer)
    if issue_metadata is not None and issue_metadata.applies_to(session) and issue_metadata.reference is not None:
        snapshot.github_issue = issue_metadata.reference.model_copy(
            update={_SUBJECT_FIELD: issue_metadata.assignment.subject}
        )
    return snapshot


async def project_session_snapshot(runtime_db: Db, session: Session, *, computer: str) -> SessionSnapshot:
    """Build one snapshot with issue identity resolved on the session's owning computer."""
    assignment = await resolve_session_issue_assignment(runtime_db, session)
    issue_metadata = await resolve_session_issue_metadata(assignment) if assignment is not None else None
    return project_session_snapshot_from_source(session, computer=computer, issue_metadata=issue_metadata)
