"""Write an item's desired pull request and reviews to GitHub, finding what is already there first."""

from __future__ import annotations

from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.core.todos_db._github_pull_requests import PullRequestBookkeeping
from teleclaude.core.workflow_store.github_io_models import GitHubPullRequest
from teleclaude.core.workflow_store.github_pull_request_io import GitHubPullRequestIO
from teleclaude.core.workflow_store.github_pull_request_reflection import (
    PullRequestReflection,
    PullRequestStage,
    delivered_comment,
    is_delivered_comment,
    opens_with_pull_request_envelope,
    review_round,
)

logger = get_logger(__name__)

_APPLIED_EVENT = "github_store_pull_request_applied"


@dataclass
class _Writes:
    """What one application changed on GitHub; an application that changed nothing is not observed."""

    created: bool = False
    updated: bool = False
    reviews_posted: int = 0
    delivery_noted: bool = False
    closed: bool = False

    @property
    def any(self) -> bool:
        return self.created or self.updated or self.reviews_posted > 0 or self.delivery_noted or self.closed


async def apply_pull_request(
    io: GitHubPullRequestIO, desired: PullRequestReflection, known: PullRequestBookkeeping
) -> bool:
    """Bring GitHub to the desired pull request, recording each step that lands in `known`.

    `known` is advanced as the writes succeed, so a failure part way leaves it holding exactly what
    GitHub now has and the next attempt repeats nothing. Returns whether GitHub now holds the desired
    reflection; False means the item's branch is not on GitHub yet, so nothing was requested, `known`
    is untouched, and the caller keeps the pull request owed for the refresh that finds the branch.
    A failure propagates for the caller to keep the pull request owed.
    """
    writes = _Writes()
    pull = await _locate(io, desired)
    if pull is None:
        if desired.stage is not PullRequestStage.OPEN:
            known.digest = desired.digest
            return True
        if not await io.branch_exists(desired.branch):
            return False
        base = await io.default_branch()
        pull = await io.create_draft_pull_request(desired.title, desired.body, desired.branch, base)
        writes.created = True
    elif (
        pull.open
        and desired.stage is PullRequestStage.OPEN
        and (pull.title, pull.body) != (desired.title, desired.body)
    ):
        await io.update_pull_request(pull.number, desired.title, desired.body)
        writes.updated = True
    if known.number != pull.number:
        known.reviews.clear()
        known.delivered_noted = False
    known.number = pull.number
    writes.reviews_posted = await _post_reviews(io, desired, known, pull.number)
    if desired.stage is PullRequestStage.DELIVERED and not known.delivered_noted:
        # A pull request already closed by the head branch's deletion still owes the delivery comment, unless
        # GitHub shows it already carries one (a lost cache must not post it twice).
        if not any(is_delivered_comment(body) for body in await io.list_own_comments(pull.number)):
            await io.comment_on_pull_request(pull.number, delivered_comment(desired.delivered_commit))
            writes.delivery_noted = True
        known.delivered_noted = True
    if desired.stage is not PullRequestStage.OPEN and pull.open:
        await io.close_pull_request(pull.number)
        writes.closed = True
    known.digest = desired.digest
    if writes.any:
        logger.info(
            _APPLIED_EVENT,
            repository=io.repository.repository,
            issue=desired.issue_number,
            pull_request=pull.number,
            stage=desired.stage,
            created=writes.created,
            updated=writes.updated,
            reviews_posted=writes.reviews_posted,
            delivery_noted=writes.delivery_noted,
            closed=writes.closed,
        )
    return True


async def _locate(io: GitHubPullRequestIO, desired: PullRequestReflection) -> GitHubPullRequest | None:
    """Find this item's own pull request: the builder App's, on its branch, naming its issue.

    An item that reuses a delivered or removed item's slug names a different issue, so it never
    adopts that item's pull request. A closed pull request is reused only to close out an item
    that is no longer open; an open item whose pull request was closed gets a new one.
    """
    own = [
        pull
        for pull in await io.list_pull_requests(desired.branch)
        if opens_with_pull_request_envelope(pull.body, desired.issue_number)
    ]
    open_pulls = [pull for pull in own if pull.open]
    if open_pulls:
        return open_pulls[0]
    if desired.stage is PullRequestStage.OPEN or not own:
        return None
    return max(own, key=lambda pull: pull.number)


async def _post_reviews(
    io: GitHubPullRequestIO, desired: PullRequestReflection, known: PullRequestBookkeeping, number: int
) -> int:
    owed = [review for review in desired.reviews if review.round not in known.reviews]
    if not owed:
        return 0
    posted_now = 0
    reviewer = await io.reviewer_login()
    posted = {
        round_number: review.commit_id
        for review in await io.list_reviews(number)
        if review.author == reviewer and (round_number := review_round(review.body)) is not None
    }
    for review in owed:
        if review.round in posted:
            known.reviews[review.round] = posted[review.round]
            continue
        await io.create_review(number, review.commit, review.event, review.body)
        known.reviews[review.round] = review.commit
        posted_now += 1
    return posted_now
