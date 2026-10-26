"""Built-in internal handler that carries a configured person's GitHub comment to the session working the item.

A relayed `issue_comment`, `pull_request_review` or `pull_request_review_comment` delivery reaches every
computer. Only the computer that hosts the session holding the item's claim delivers it, as that person's
message. Admission rests on structural facts alone — sender type, repository association and the
configured people — and runs before any comment text is read into a command.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from githubkit.webhooks import parse_obj
from githubkit_schemas.v2026_03_10.models import (
    WebhookIssueCommentCreated,
    WebhookPullRequestReviewCommentCreated,
    WebhookPullRequestReviewSubmitted,
)
from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.inbound_types import GITHUB_ACTOR_ID_PREFIX
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.origins import InputOrigin
from teleclaude.core.workflow_store.github_store import find_github_work_item
from teleclaude.hooks.webhook_models import Contract, HookEvent
from teleclaude.types.commands import ProcessMessageCommand

logger = get_logger(__name__)

_ACTOR_ID_TEMPLATE = GITHUB_ACTOR_ID_PREFIX + "{login}"
_OCCURRENCE_KEY_TEMPLATE = "github:{event_type}:{comment_id}"
_ATTRIBUTION_TEMPLATE = "{name} (@{login}) {act}: {url}"
_ATTRIBUTION_WITH_TEXT_TEMPLATE = "{attribution}\n\n{text}"
_LOGIN_FIELD = "login"
_PLATFORM = "github"
_USER_ACCOUNT_TYPE = "User"
_REFUSED_EVENT = "github_comment_not_delivered"
_DELIVERED_EVENT = "github_comment_delivered"
_REJECTED_EVENT = "github_comment_rejected_by_session"
_NO_TEXT = ""


class GitHubCommentEvent(StrEnum):
    """GitHub delivery types that carry a person's words."""

    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST_REVIEW = "pull_request_review"
    PULL_REQUEST_REVIEW_COMMENT = "pull_request_review_comment"


class RepositoryAssociation(StrEnum):
    """How GitHub relates a comment's author to the repository."""

    OWNER = "OWNER"
    MEMBER = "MEMBER"
    COLLABORATOR = "COLLABORATOR"
    CONTRIBUTOR = "CONTRIBUTOR"
    FIRST_TIMER = "FIRST_TIMER"
    FIRST_TIME_CONTRIBUTOR = "FIRST_TIME_CONTRIBUTOR"
    MANNEQUIN = "MANNEQUIN"
    NONE = "NONE"


_ADMITTED_ASSOCIATIONS = frozenset(
    {RepositoryAssociation.OWNER, RepositoryAssociation.MEMBER, RepositoryAssociation.COLLABORATOR}
)


class CommentAct(StrEnum):
    """What the person did, as the session reads it."""

    COMMENTED = "commented"
    APPROVED = "approved"
    REQUESTED_CHANGES = "requested changes"
    COMMENTED_ON_LINE = "commented on a line"


class ReviewState(StrEnum):
    """Review states GitHub reports for a submitted review."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class Refusal(StrEnum):
    """Why a delivery reached no session; logged without the comment text."""

    UNPARSEABLE = "unparseable"
    NOT_A_NEW_COMMENT = "not_a_new_comment"
    NOT_A_USER = "not_a_user"
    NOT_A_COLLABORATOR = "not_a_collaborator"
    UNKNOWN_PERSON = "unknown_person"
    NO_ITEM = "no_item"
    NO_CLAIM = "no_claim"
    CLAIM_NOT_HERE = "claim_not_here"
    SESSION_REJECTED = "session_rejected"


_REVIEW_ACTS: dict[str, CommentAct] = {
    ReviewState.APPROVED: CommentAct.APPROVED,
    ReviewState.CHANGES_REQUESTED: CommentAct.REQUESTED_CHANGES,
}


@dataclass(frozen=True)
class _Comment:
    """The facts of one person's words on GitHub that admission and delivery need."""

    repository_id: int
    number: int
    comment_id: int
    sender_login: str
    sender_type: str
    association: RepositoryAssociation
    act: CommentAct
    url: str
    text: str


def _parse(event: HookEvent) -> _Comment | Refusal:
    """Read a delivery through GitHubKit's webhook models; the refusal when it is not a readable new comment or review."""
    payload = dict(event.payload)
    try:
        match event.type:
            case GitHubCommentEvent.ISSUE_COMMENT:
                issue_comment = parse_obj(GitHubCommentEvent.ISSUE_COMMENT.value, payload)
                if not isinstance(issue_comment, WebhookIssueCommentCreated):
                    return Refusal.NOT_A_NEW_COMMENT
                return _Comment(
                    repository_id=issue_comment.repository.id,
                    number=issue_comment.issue.number,
                    comment_id=issue_comment.comment.id,
                    sender_login=issue_comment.sender.login,
                    sender_type=issue_comment.sender.type,
                    association=RepositoryAssociation(issue_comment.comment.author_association),
                    act=CommentAct.COMMENTED,
                    url=issue_comment.comment.html_url,
                    text=issue_comment.comment.body,
                )
            case GitHubCommentEvent.PULL_REQUEST_REVIEW:
                review = parse_obj(GitHubCommentEvent.PULL_REQUEST_REVIEW.value, payload)
                if not isinstance(review, WebhookPullRequestReviewSubmitted):
                    return Refusal.NOT_A_NEW_COMMENT
                return _Comment(
                    repository_id=review.repository.id,
                    number=review.pull_request.number,
                    comment_id=review.review.id,
                    sender_login=review.sender.login,
                    sender_type=review.sender.type,
                    association=RepositoryAssociation(review.review.author_association),
                    act=_REVIEW_ACTS.get(review.review.state.lower(), CommentAct.COMMENTED),
                    url=review.review.html_url,
                    text=review.review.body or _NO_TEXT,
                )
            case GitHubCommentEvent.PULL_REQUEST_REVIEW_COMMENT:
                line_comment = parse_obj(GitHubCommentEvent.PULL_REQUEST_REVIEW_COMMENT.value, payload)
                if not isinstance(line_comment, WebhookPullRequestReviewCommentCreated):
                    return Refusal.NOT_A_NEW_COMMENT
                return _Comment(
                    repository_id=line_comment.repository.id,
                    number=line_comment.pull_request.number,
                    comment_id=line_comment.comment.id,
                    sender_login=line_comment.sender.login,
                    sender_type=line_comment.sender.type,
                    association=RepositoryAssociation(line_comment.comment.author_association),
                    act=CommentAct.COMMENTED_ON_LINE,
                    url=line_comment.comment.html_url,
                    text=line_comment.comment.body,
                )
            case _:
                return Refusal.NOT_A_NEW_COMMENT
    except ValidationError:
        return Refusal.UNPARSEABLE


def _refuse(refusal: Refusal, event: HookEvent, comment: _Comment | None) -> None:
    logger.info(
        _REFUSED_EVENT,
        reason=refusal,
        event_type=event.type,
        repository_id=comment.repository_id if comment is not None else None,
        number=comment.number if comment is not None else None,
    )


async def handle_github_event(event: HookEvent, contract: Contract) -> None:
    """Deliver one admitted person's comment or review to the session holding the item's claim."""
    del contract
    comment = _parse(event)
    if isinstance(comment, Refusal):
        _refuse(comment, event, None)
        return
    if comment.sender_type != _USER_ACCOUNT_TYPE:
        _refuse(Refusal.NOT_A_USER, event, comment)
        return
    if comment.association not in _ADMITTED_ASSOCIATIONS:
        _refuse(Refusal.NOT_A_COLLABORATOR, event, comment)
        return
    person = get_identity_resolver().resolve(_PLATFORM, {_LOGIN_FIELD: comment.sender_login})
    if not person.person_slug:
        _refuse(Refusal.UNKNOWN_PERSON, event, comment)
        return

    item = await asyncio.to_thread(find_github_work_item, comment.repository_id, comment.number)
    if item is None:
        _refuse(Refusal.NO_ITEM, event, comment)
        return
    if item.active_runner is None:
        _refuse(Refusal.NO_CLAIM, event, comment)
        return
    if not await is_live_session_id(db, item.active_runner):
        _refuse(Refusal.CLAIM_NOT_HERE, event, comment)
        return

    attribution = _ATTRIBUTION_TEMPLATE.format(
        name=person.person_name or comment.sender_login,
        login=comment.sender_login,
        act=comment.act,
        url=comment.url,
    )
    text = (
        _ATTRIBUTION_WITH_TEXT_TEMPLATE.format(attribution=attribution, text=comment.text)
        if comment.text
        else attribution
    )
    command = ProcessMessageCommand(
        session_id=item.active_runner,
        text=text,
        origin=InputOrigin.GITHUB.value,
        text_kind=TranscriptEntryKind.ORDINARY,
        source_feature=InjectedTextSourceFeature.GITHUB,
        occurrence_key=_OCCURRENCE_KEY_TEMPLATE.format(event_type=event.type, comment_id=comment.comment_id),
        actor_id=_ACTOR_ID_TEMPLATE.format(login=comment.sender_login),
        actor_name=person.person_name,
        source_message_id=str(comment.comment_id),
        source_channel_id=comment.url,
    )
    try:
        await get_command_service().process_message(command)
    except SessionMessageRejectedError as error:
        logger.warning(_REJECTED_EVENT, reason=Refusal.SESSION_REJECTED, rejection=error.reason, number=comment.number)
        return
    logger.info(_DELIVERED_EVENT, session_id=item.active_runner, number=comment.number, act=comment.act)
