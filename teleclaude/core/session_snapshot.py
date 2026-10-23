"""Project stored sessions and locally resolved assigned issue links for viewers."""

from __future__ import annotations

import asyncio
import re
from configparser import Error as ConfigError
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from instrukt_ai_logging import get_logger
from pydantic import HttpUrl

from teleclaude.core.models._snapshot import SessionSnapshot
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.project_manifest import load_registered_roots
from teleclaude.types.github_issue import GitHubIssueReference
from teleclaude.types.work_subject import WorkSubjectParameter

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

_SUBJECT_FIELD = "subject"
_LOOKUP_UNAVAILABLE_EVENT = "session_github_issue_lookup_unavailable"
_REPOSITORY_CONFIG: Final = "repository"
_ORIGIN_SECTION = 'remote "origin"'
_URL_OPTION = "url"
_GITHUB_HOST = "github.com"
_GIT_USER = "git"
_SCP_ORIGIN = re.compile(r"git@github\.com:(.+)", re.IGNORECASE)
_REPOSITORY_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
_PATH_SEPARATOR = "/"
_GIT_SUFFIX = ".git"
_INVALID_REPOSITORIES = frozenset({".", ".."})
_ISSUE_SEPARATOR = "#"
_ISSUES_SEGMENT = "issues"
_ISSUE_URL = "https://github.com/{repository}/issues/{number}"


class _RemoteScheme(StrEnum):
    HTTPS = "https"
    SSH = "ssh"


@dataclass(frozen=True)
class SessionIssueAssignment:
    """Recorded assignment identity used to decide whether local navigation still applies."""

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


def _origin_repository(origin: str) -> str | None:
    """Read only a GitHub.com repository path from a credential-free HTTPS or Git SSH origin."""
    if any(character.isspace() for character in origin):
        return None
    scp = _SCP_ORIGIN.fullmatch(origin)
    if scp is not None:
        path = scp.group(1)
    else:
        parsed = urlsplit(origin)
        if parsed.hostname != _GITHUB_HOST or parsed.password is not None or parsed.query or parsed.fragment:
            return None
        if parsed.scheme == _RemoteScheme.HTTPS:
            if parsed.username is not None or parsed.port not in (None, 443):
                return None
        elif parsed.scheme == _RemoteScheme.SSH:
            if parsed.username not in (None, _GIT_USER) or parsed.port not in (None, 22):
                return None
        else:
            return None
        path = parsed.path
    repository = path.removeprefix(_PATH_SEPARATOR).removesuffix(_PATH_SEPARATOR).removesuffix(_GIT_SUFFIX)
    if not _REPOSITORY_PATH.fullmatch(repository) or repository.split(_PATH_SEPARATOR)[1] in _INVALID_REPOSITORIES:
        return None
    return repository


def _assigned_number(selector: str, repository: str) -> int | None:
    """Resolve the recorded display selector without creating or validating workflow identity."""
    if any(character.isspace() for character in selector):
        return None
    number = selector
    if not (selector.isascii() and selector.isdecimal()):
        parsed = urlsplit(selector)
        if parsed.scheme:
            parts = parsed.path.split(_PATH_SEPARATOR)
            if (
                parsed.scheme != _RemoteScheme.HTTPS
                or parsed.hostname != _GITHUB_HOST
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
                or len(parts) != 5
                or parts[0]
                or parts[3] != _ISSUES_SEGMENT
                or _PATH_SEPARATOR.join(parts[1:3]).casefold() != repository.casefold()
            ):
                return None
            number = parts[4]
        else:
            selected_repository, separator, number = selector.partition(_ISSUE_SEPARATOR)
            if not separator or selected_repository.casefold() != repository.casefold():
                return None
    if not number.isascii() or not number.isdecimal():
        return None
    value = int(number)
    return value if value > 0 else None


def _local_issue_reference(project_path: str, selector: str) -> GitHubIssueReference | None:
    """Compose optional navigation from a registered project and its one declared Git origin."""
    try:
        root = resolve_owning_checkout(Path(project_path))
        if root is None or not any(
            entry.is_present and entry.path.resolve() == root for entry in load_registered_roots(strict=True)
        ):
            return None
        with Repo(root) as repository, repository.config_reader(config_level=_REPOSITORY_CONFIG) as config:
            if not config.has_section(_ORIGIN_SECTION) or not config.has_option(_ORIGIN_SECTION, _URL_OPTION):
                return None
            origins = config.get_values(_ORIGIN_SECTION, _URL_OPTION)
        if len(origins) != 1 or not isinstance(origins[0], str):
            return None
        github_repository = _origin_repository(origins[0])
        if github_repository is None:
            return None
        number = _assigned_number(selector, github_repository)
        if number is None:
            return None
        return GitHubIssueReference(
            number=number, url=HttpUrl(_ISSUE_URL.format(repository=github_repository, number=number))
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        ConfigError,
        GitCommandError,
        InvalidGitRepositoryError,
        NoSuchPathError,
    ) as error:
        # Navigation is optional; unreadable local Git/registry state never hides the session.
        logger.warning(_LOOKUP_UNAVAILABLE_EVENT, project_path=project_path, error_type=type(error).__name__)
        return None


async def resolve_session_issue_assignment(runtime_db: Db, session: Session) -> SessionIssueAssignment | None:
    """Read the applicable recorded issue assignment without doing navigation I/O."""
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
    """Resolve optional local navigation for an already-read assignment, without a provider request."""
    reference = await asyncio.to_thread(
        _local_issue_reference,
        assignment.project_path,
        assignment.selector,
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
