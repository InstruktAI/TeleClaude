"""A followed repository's newest green main revision, read for an installation whose computer receives no relay.

The answer applies the one required-check rule integration owns (``ci_run_outcomes``: every required check has a
green run for the revision, and a revision that declares no check is never green). It is read from GitHub run
results without a credential, so a public source answers for an installation outside the source's own cluster.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from teleclaude.constants import MAIN_BRANCH
from teleclaude.github.actions import GitHubActionsReader, GitHubActionsRefused, PublicRepository

_NEWEST_GREEN_CANDIDATES: Final = 10
_NO_GREEN_DETAIL: Final = "none of the newest {count} main revisions has every required check green"
_REACHED_ACTIVE_DETAIL: Final = "no main revision newer than the active release's has every required check green"
_NO_COMMITS_DETAIL: Final = "the repository lists no main commit"
_EMPTY_DETAIL: Final = ""


class NewestGreenStatus(StrEnum):
    """What the query could say: a green revision, that none of the revisions it looked at is green, or nothing."""

    GREEN = "green"
    NONE_GREEN = "none_green"
    CANNOT_TELL = "cannot_tell"


@dataclass(frozen=True)
class NewestGreenAnswer:
    """The newest green main revision of a followed repository, or why there is none to name."""

    status: NewestGreenStatus
    revision: str | None
    detail: str


async def newest_green_main_revision(
    repository: str, required_checks_at: Callable[[str], tuple[str, ...]], stop_at: str | None
) -> NewestGreenAnswer:
    """The newest main revision of a followed repository whose required checks all have green runs.

    ``repository`` is the canonical ``owner/name`` of a repository this computer holds no App for, read without a
    credential. The caller supplies the checks each revision declares, because only it holds the repository to read
    the declaration from; a revision whose declaration names no required check is never green, matching the rule
    that no checks means no green. The walk goes newest first and stops at the first green revision, at
    ``stop_at`` (the active release's revision, past which nothing is newer), or after a small fixed number of
    candidates, so one query costs one commit-list request plus at most that many run-list requests. A refusal
    (not found, rate limited, unavailable) answers that it cannot tell.
    """
    reader = GitHubActionsReader(PublicRepository(repository))
    try:
        candidates = await reader.recent_commits(MAIN_BRANCH, _NEWEST_GREEN_CANDIDATES)
        if not candidates:
            return NewestGreenAnswer(NewestGreenStatus.CANNOT_TELL, None, _NO_COMMITS_DETAIL)
        for revision in candidates:
            if revision == stop_at:
                return NewestGreenAnswer(NewestGreenStatus.NONE_GREEN, None, _REACHED_ACTIVE_DETAIL)
            required_checks = await asyncio.to_thread(required_checks_at, revision)
            if required_checks and await reader.revision_green(revision, required_checks, MAIN_BRANCH) is not None:
                return NewestGreenAnswer(NewestGreenStatus.GREEN, revision, _EMPTY_DETAIL)
    except GitHubActionsRefused as refusal:
        return NewestGreenAnswer(NewestGreenStatus.CANNOT_TELL, None, str(refusal))
    return NewestGreenAnswer(NewestGreenStatus.NONE_GREEN, None, _NO_GREEN_DETAIL.format(count=len(candidates)))
