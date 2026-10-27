"""The messages computers exchange about the conversation: a captured turn handed to the fleet master, the position
the master finds on a destination, and a limit response a computer tells the master of.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

CONVERSATION_API_PREFIX = "/api/conversation"
POST_TURN_ROUTE = "/post"
POSITION_ROUTE = "/position"
LIMIT_NOTICE_ROUTE = "/limit"
POST_TURN_PATH = CONVERSATION_API_PREFIX + POST_TURN_ROUTE
POSITION_PATH = CONVERSATION_API_PREFIX + POSITION_ROUTE
LIMIT_NOTICE_PATH = CONVERSATION_API_PREFIX + LIMIT_NOTICE_ROUTE


class Outcome(StrEnum):
    """How the master answered a request."""

    OK = "ok"
    DEFERRED = "deferred"
    REFUSED = "refused"


class RefusalCause(StrEnum):
    """Why the master refused a request, without any content."""

    NOT_MASTER = "not_master"
    ROLE_UNMAPPED = "role_unmapped"
    CREDENTIAL_REFUSED = "credential_refused"
    VALIDATION_REFUSED = "validation_refused"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Destination(_Wire):
    """The issue or pull request a turn goes on, in the repository the project's store names."""

    repository_id: int
    repository: str = Field(min_length=3)
    number: int = Field(gt=0)


class PostTurnRequest(_Wire):
    """A captured turn handed over: the comments still to be written, in order, as the App chosen for its session.

    ``possibly_sent`` is set when an earlier hand-over may have written some of them without the sender learning of
    it; the master then reads the destination first and writes only what is not already there.
    """

    destination: Destination
    app_id: int = Field(gt=0)
    session_id: str = Field(min_length=1)
    ordinal: int = Field(gt=0)
    bodies: list[str] = Field(min_length=1)
    possibly_sent: bool = False


class PostTurnResponse(_Wire):
    """What the master did with a hand-over: how many comments are now on GitHub, in order from the first given.

    ``uncertain`` is set when the master cannot tell whether the comment it was creating when it stopped reached
    GitHub, as when the connection broke before the answer, and when it was asked to read the destination first
    (``possibly_sent``) and stopped before it had; the sender then keeps the turn marked as possibly sent.
    """

    outcome: Outcome
    written: int = 0
    uncertain: bool = False
    retry_at: datetime | None = None
    cause: RefusalCause | None = None


class PositionRequest(_Wire):
    """Ask which turns of a session the destination already holds, and which of their comments."""

    destination: Destination
    app_id: int = Field(gt=0)
    session_id: str = Field(min_length=1)


class PositionTurn(_Wire):
    """One turn of the session found on the destination: its comment count and which of them are there."""

    ordinal: int
    parts: int
    present_parts: list[int]


class PositionResponse(_Wire):
    """The session's turns the master found on the destination, or why it could not look."""

    outcome: Outcome
    turns: list[PositionTurn] = Field(default_factory=list)
    retry_at: datetime | None = None
    cause: RefusalCause | None = None


class LimitNoticeRequest(_Wire):
    """A limit response a computer received, with the time it names for requests to resume, if any."""

    resume_at: datetime | None = None


class LimitNoticeResponse(_Wire):
    """When the master's conversation requests resume after the notice."""

    paused_until: datetime
