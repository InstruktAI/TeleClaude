"""Project stored sessions and their verified issue assignments for viewers."""

from __future__ import annotations

import asyncio
import subprocess
import time
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


async def project_session_snapshot(runtime_db: Db, session: Session, *, computer: str) -> SessionSnapshot:
    """Build one snapshot with issue identity resolved on the session's owning computer."""
    snapshot = SessionSnapshot.from_db_session(session, computer=computer)
    if session.command is None or session.project_path is None:
        return snapshot
    handover = await runtime_db.get_startup_handover(session.session_id)
    invocation = handover.intent.invocation if handover is not None else None
    if invocation is None:
        return snapshot
    parameters = dict(invocation.parameters)
    selector = parameters.get(WorkSubjectParameter.ISSUE)
    if selector is None:
        return snapshot
    reference = await asyncio.to_thread(
        _issue_lookup_attempt, session.project_path, selector, int(time.monotonic() / _LOOKUP_RETRY_SECONDS)
    )
    if reference is not None:
        subject = parameters.get(WorkSubjectParameter.BRANCH) or parameters.get(WorkSubjectParameter.SLUG)
        snapshot.github_issue = reference.model_copy(update={_SUBJECT_FIELD: subject})
    return snapshot
