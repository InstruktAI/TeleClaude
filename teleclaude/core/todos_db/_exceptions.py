"""Typed exceptions for todo database contract refusals."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from typing_extensions import TypedDict

_REMOVE_LIVE_WORK_FEEDBACK = (
    "Removal is blocked while live work holds this todo. Finish or release that work before trying again."
)
_REVIEWER_CONFLICT_WORK_FEEDBACK_WITH_HOLDER = (
    "A reviewer is already working on {subject}; continue with that session using {reuse_command}."
)
_REVIEWER_CONFLICT_WORK_FEEDBACK = "A reviewer is already working on {subject}."
_CLAIM_CONFLICT_WORK_FEEDBACK_WITH_HOLDER = (
    "Another session is already working on {slug}; contact it with `telec sessions send {holder} <message>`."
)
_CLAIM_CONFLICT_WORK_FEEDBACK = "Another lifecycle run is already working on {slug}; try again after it finishes."
_CLAIM_CONFLICT_WORK_FEEDBACK_ON_COMPUTER = (
    "Session {holder} on {computer} is already working on {slug}; contact it with "
    "`telec sessions send {holder} <message> --computer {computer}`."
)
_CLAIM_CONFLICT_WORK_FEEDBACK_UNANSWERED = (
    "Session {holder} holds {slug}, and {unanswered} did not answer for it, so it is still held; "
    "end that session or bring those computers back."
)
_CLAIM_CONFLICT_SUMMARY_ON_COMPUTER = "ClaimConflict: {slug} is already driven by session {holder} on {computer}"
_CLAIM_CONFLICT_SUMMARY_UNANSWERED = (
    "ClaimConflict: {slug} is held by session {holder}; no computer answered for it ({unanswered})"
)
_COMPUTER_SEPARATOR = ", "
_ADMISSION_UNAVAILABLE_WORK_FEEDBACK = (
    "The start of {slug} was not admitted: {reason}. Nothing was created; try again once the fleet is reachable."
)
_ADMISSION_UNAVAILABLE_SUMMARY = "AdmissionUnavailable: the start of {slug} was not admitted: {reason}"
_DRIVER_START_BUSY_WORK_FEEDBACK_WITH_START = (
    "Another start of {slug} is in progress as session {in_flight}; contact it with "
    "`telec sessions send {in_flight} <message>`."
)
_DRIVER_START_BUSY_WORK_FEEDBACK_WITH_REFUSAL = "Another start of {slug} is in progress: {refusal}"
_DRIVER_START_BUSY_WORK_FEEDBACK = "Another start of {slug} is in progress; try again after it finishes."
_DRIVER_START_BUSY_SUMMARY_WITH_START = "DriverStartBusy: another start of {slug} is in progress as session {in_flight}"
_DRIVER_START_BUSY_SUMMARY_WITH_REFUSAL = "DriverStartBusy: another start of {slug} is in progress: {refusal}"
_DRIVER_START_BUSY_SUMMARY = "DriverStartBusy: another start of {slug} is in progress"
_LANE_CROSSING_WORK_FEEDBACK = (
    "This todo is held in the {held_lane} lane and cannot be started from {requested_lane}. {sanctioned_path}."
)


class ClaimConflictField(StrEnum):
    """The payload fields of a :class:`ClaimConflict` that cross a computer boundary."""

    HOLDER = "holder"
    COMPUTER = "computer"
    UNANSWERED = "unanswered"


class DriverStartBusyField(StrEnum):
    """The payload fields of a :class:`DriverStartBusy` that cross a computer boundary."""

    IN_FLIGHT = "in_flight"


class AdmissionUnavailableField(StrEnum):
    """The payload fields of an :class:`AdmissionUnavailable` that cross a computer boundary."""

    REASON = "reason"
    DETAIL = "detail"


def _text_field(payload: Mapping[str, object], field: StrEnum) -> str | None:
    """A non-empty text field of a received payload, or ``None`` when it is absent or not text."""
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


class OperationErrorPayload(TypedDict):
    """Structured operation failure payload contract."""

    kind: str


class RemoveRefusedLiveWorkErrorPayload(OperationErrorPayload):
    """Structured live-work refusal payload for todo removal."""

    slug: str
    session_ids: list[str]
    operation_ids: list[str]
    claim_holder: str | None


class ClaimConflictErrorPayload(OperationErrorPayload):
    """Structured driver-start conflict payload."""

    slug: str
    holder: str | None
    computer: str | None
    unanswered: list[str]


class DriverStartBusyErrorPayload(OperationErrorPayload):
    """Structured payload for a driver start refused while another start of the todo is in progress."""

    slug: str
    in_flight: str | None
    refusal: str | None


class OperationFailure(Exception):
    """Base class for operation failures with structured API payloads."""

    error_kind: str
    work_feedback: str | None = None

    def to_error_payload(self) -> OperationErrorPayload:
        """Return the machine-readable operation error payload."""
        raise NotImplementedError

    def summary(self) -> str:
        """Return a short human-readable error summary."""
        return f"{type(self).__name__}: {self}"


class RemoveRefusedLiveWork(OperationFailure):
    """Soft-remove refused because live work still holds the todo."""

    error_kind = "remove_refused_live_work"

    def __init__(
        self,
        *,
        slug: str,
        session_ids: list[str],
        operation_ids: list[str],
        claim_holder: str | None,
    ) -> None:
        self.slug = slug
        self.session_ids = session_ids
        self.operation_ids = operation_ids
        self.claim_holder = claim_holder
        self.work_feedback = _REMOVE_LIVE_WORK_FEEDBACK
        super().__init__(slug)

    def to_error_payload(self) -> RemoveRefusedLiveWorkErrorPayload:
        return {
            "kind": self.error_kind,
            "slug": self.slug,
            "session_ids": self.session_ids,
            "operation_ids": self.operation_ids,
            "claim_holder": self.claim_holder,
        }

    def summary(self) -> str:
        holders = len(self.session_ids) + len(self.operation_ids) + int(self.claim_holder is not None)
        return f"RemoveRefusedLiveWork: {holders} live holder(s) block removal of {self.slug}"


class ReviewerConflictErrorPayload(OperationErrorPayload):
    """Structured reviewer-conflict payload for any reviewer-conflict subject.

    Applies to every slug-bound reviewer (``sdlc/review-build``,
    ``sdlc/review-plan``, ``sdlc/review-architecture``) as well as the
    slugless commit-review subject (``sdlc/review-commits``).
    """

    subject: str
    holder: str | None
    reuse_command: str


class ReviewerConflict(OperationFailure):
    """Reviewer-start refused because a live reviewer already holds this subject.

    Raised by the create-door dedup guard for a reviewer launch (``REVIEWER``
    launch class). ``ClaimConflict`` is slug-shaped by construction (a required
    ``slug: str``) and cannot express a commit-review subject, whose identity is
    the project and initiating driver rather than a todo slug — so this is a
    sibling member of the same ``OperationFailure`` family, not a widening of
    ``ClaimConflict`` or a second guard/mapping. ``subject`` is a human-readable
    description of what is already reviewed (a slug+command pair, or a project
    and initiator for commit review); ``reuse_command`` is the concrete command
    that addresses the holder instead of starting a second reviewer.
    """

    error_kind = "reviewer_conflict"

    def __init__(self, *, subject: str, holder: str | None, reuse_command: str) -> None:
        self.subject = subject
        self.holder = holder
        self.reuse_command = reuse_command
        self.work_feedback = (
            _REVIEWER_CONFLICT_WORK_FEEDBACK_WITH_HOLDER.format(subject=subject, reuse_command=reuse_command)
            if holder
            else _REVIEWER_CONFLICT_WORK_FEEDBACK.format(subject=subject)
        )
        super().__init__(subject)

    def to_error_payload(self) -> ReviewerConflictErrorPayload:
        return {
            "kind": self.error_kind,
            "subject": self.subject,
            "holder": self.holder,
            "reuse_command": self.reuse_command,
        }

    def summary(self) -> str:
        if self.holder:
            return (
                f"ReviewerConflict: {self.subject} already has a live reviewer "
                f"(session {self.holder}) — reuse it: {self.reuse_command}"
            )
        return f"ReviewerConflict: {self.subject} already has a live reviewer"


class ReviewerIdentityUnresolvedErrorPayload(OperationErrorPayload):
    """Structured payload for a reviewer subject whose dedup key cannot be established."""

    subject: str


class ReviewerIdentityUnresolved(OperationFailure):
    """Reviewer-start refused because the caller carries no identity to key dedup on.

    Commit review's subject is ``(project, driver, command, thinking mode)`` —
    there is no todo slug to key on instead. The driver is the caller's session,
    or, for a caller with no session, its authenticated human. A caller that
    resolves to neither has nothing to look up a prior holder by. Admitting it
    silently would bypass dedup entirely for that caller, which is the gap R1
    requires closed with no escape hatch — so the create door refuses rather
    than starting an unkeyed reviewer. This is a sibling member of the same ``OperationFailure`` family
    as ``ReviewerConflict``, not a widening of it: unlike a real conflict,
    there is no live holder to name.
    """

    error_kind = "reviewer_identity_unresolved"

    def __init__(self, *, subject: str) -> None:
        self.subject = subject
        super().__init__(subject)

    def to_error_payload(self) -> ReviewerIdentityUnresolvedErrorPayload:
        return {"kind": self.error_kind, "subject": self.subject}

    def summary(self) -> str:
        return f"ReviewerIdentityUnresolved: {self.subject} has no resolvable caller identity to dedup against"


class ClaimConflict(OperationFailure):
    """Driver-start refused because a live driver already holds the slug.

    Raised by the create-door dedup guard and the operator op door when a second
    lifecycle driver would be started for a slug a live driver already holds. The
    holder session id is carried so the operator toast and the HTTP 409 detail can
    name who is in the way.
    """

    error_kind = "driver_start_conflict"

    def __init__(
        self,
        *,
        slug: str,
        holder: str | None,
        computer: str | None = None,
        unanswered: tuple[str, ...] = (),
    ) -> None:
        self.slug = slug
        self.holder = holder
        self.computer = computer
        self.unanswered = unanswered
        if holder and unanswered:
            self.work_feedback = _CLAIM_CONFLICT_WORK_FEEDBACK_UNANSWERED.format(
                slug=slug, holder=holder, unanswered=_COMPUTER_SEPARATOR.join(unanswered)
            )
        elif holder and computer:
            self.work_feedback = _CLAIM_CONFLICT_WORK_FEEDBACK_ON_COMPUTER.format(
                slug=slug, holder=holder, computer=computer
            )
        elif holder:
            self.work_feedback = _CLAIM_CONFLICT_WORK_FEEDBACK_WITH_HOLDER.format(slug=slug, holder=holder)
        else:
            self.work_feedback = _CLAIM_CONFLICT_WORK_FEEDBACK.format(slug=slug)
        super().__init__(slug)

    def to_error_payload(self) -> ClaimConflictErrorPayload:
        return ClaimConflictErrorPayload(
            kind=self.error_kind,
            slug=self.slug,
            holder=self.holder,
            computer=self.computer,
            unanswered=list(self.unanswered),
        )

    @classmethod
    def from_error_payload(cls, slug: str, payload: Mapping[str, object]) -> ClaimConflict:
        """Rebuild the conflict another computer declared, from the payload it carried."""
        unanswered = payload.get(ClaimConflictField.UNANSWERED)
        return cls(
            slug=slug,
            holder=_text_field(payload, ClaimConflictField.HOLDER),
            computer=_text_field(payload, ClaimConflictField.COMPUTER),
            unanswered=tuple(item for item in unanswered if isinstance(item, str))
            if isinstance(unanswered, list)
            else (),
        )

    def summary(self) -> str:
        if self.holder and self.unanswered:
            return _CLAIM_CONFLICT_SUMMARY_UNANSWERED.format(
                slug=self.slug, holder=self.holder, unanswered=_COMPUTER_SEPARATOR.join(self.unanswered)
            )
        if self.holder and self.computer:
            return _CLAIM_CONFLICT_SUMMARY_ON_COMPUTER.format(
                slug=self.slug, holder=self.holder, computer=self.computer
            )
        if self.holder:
            return f"ClaimConflict: {self.slug} is already driven by session {self.holder}"
        return f"ClaimConflict: {self.slug} is already driven"


class AdmissionUnavailableReason(StrEnum):
    """Why a GitHub-backed start could not be decided, so nothing was created."""

    NO_LIVE_MASTER = "no live master computer admits starts"
    CONFLICTING_MASTERS = "more than one computer claims to be the master"
    FLEET_NOT_OBSERVABLE = "the fleet cannot be observed"
    MASTER_CANNOT_CARRY = "the master cannot carry the admission request"
    MASTER_DID_NOT_ANSWER = "the master did not answer"
    UNDECIDED_WITHIN_BUDGET = "the start was not decided within its budget"
    NOT_THE_MASTER = "this computer is not the master"
    REFUSED_AT_CREATE_DOOR = "the create door refused the start as undecided"
    ADMISSION_FAILED = "the admission failed before it was decided"
    NO_LIVE_TODO = "the todo has no live state to record a claim on"


class AdmissionUnavailableErrorPayload(OperationErrorPayload):
    """Structured payload for a start that could not be decided."""

    slug: str
    reason: str
    detail: str | None


class AdmissionUnavailable(OperationFailure):
    """A GitHub-backed driver start could not be decided, so it was refused and created nothing.

    The fleet's master admits every start of a GitHub-backed todo. When no unique live master can be
    reached, or it does not answer within the start's budget, the start is refused rather than decided
    by a rule that could admit a second driver. ``reason`` names which; ``detail`` carries the transport
    or fleet text when there is one.
    """

    error_kind = "driver_admission_unavailable"

    def __init__(self, *, slug: str, reason: AdmissionUnavailableReason, detail: str | None = None) -> None:
        self.slug = slug
        self.reason = reason
        self.detail = detail
        reason_text = f"{reason.value} ({detail})" if detail else reason.value
        self.work_feedback = _ADMISSION_UNAVAILABLE_WORK_FEEDBACK.format(slug=slug, reason=reason_text)
        super().__init__(slug)

    def to_error_payload(self) -> AdmissionUnavailableErrorPayload:
        return AdmissionUnavailableErrorPayload(
            kind=self.error_kind, slug=self.slug, reason=self.reason.name, detail=self.detail
        )

    @classmethod
    def from_error_payload(cls, slug: str, payload: Mapping[str, object]) -> AdmissionUnavailable | None:
        """Rebuild the refusal another computer declared; ``None`` when its reason is not one this release knows."""
        declared = _text_field(payload, AdmissionUnavailableField.REASON)
        if declared is None or declared not in AdmissionUnavailableReason.__members__:
            return None
        return cls(
            slug=slug,
            reason=AdmissionUnavailableReason[declared],
            detail=_text_field(payload, AdmissionUnavailableField.DETAIL),
        )

    def summary(self) -> str:
        reason_text = f"{self.reason.value} ({self.detail})" if self.detail else self.reason.value
        return _ADMISSION_UNAVAILABLE_SUMMARY.format(slug=self.slug, reason=reason_text)


class DriverStartBusy(OperationFailure):
    """Driver-start refused because another start of the same todo is in progress.

    Raised by the admission section when a start finds the section held by another
    start of the todo. The refusal never waits: a colliding start is a concurrent
    start of the same todo, which is exactly the start that must lose. ``in_flight``
    is the session the holding start is creating or claiming, so the refusal names
    who is in the way just as :class:`ClaimConflict` does. A caller that learns of the
    refusal across the create door's HTTP boundary holds the refusal's prose, which names
    that session; it carries the prose as ``refusal`` and reports it unchanged, never
    parsing it for the identity.
    """

    error_kind = "driver_start_busy"

    def __init__(self, *, slug: str, in_flight: str | None = None, refusal: str | None = None) -> None:
        self.slug = slug
        self.in_flight = in_flight
        self.refusal = refusal
        if in_flight:
            self.work_feedback = _DRIVER_START_BUSY_WORK_FEEDBACK_WITH_START.format(slug=slug, in_flight=in_flight)
        elif refusal:
            self.work_feedback = _DRIVER_START_BUSY_WORK_FEEDBACK_WITH_REFUSAL.format(slug=slug, refusal=refusal)
        else:
            self.work_feedback = _DRIVER_START_BUSY_WORK_FEEDBACK.format(slug=slug)
        super().__init__(slug)

    def to_error_payload(self) -> DriverStartBusyErrorPayload:
        return DriverStartBusyErrorPayload(
            kind=self.error_kind, slug=self.slug, in_flight=self.in_flight, refusal=self.refusal
        )

    @classmethod
    def from_error_payload(cls, slug: str, payload: Mapping[str, object]) -> DriverStartBusy:
        """Rebuild the refusal another computer declared, naming the start it found in progress."""
        return cls(slug=slug, in_flight=_text_field(payload, DriverStartBusyField.IN_FLIGHT))

    def summary(self) -> str:
        if self.in_flight:
            return _DRIVER_START_BUSY_SUMMARY_WITH_START.format(slug=self.slug, in_flight=self.in_flight)
        if self.refusal:
            return _DRIVER_START_BUSY_SUMMARY_WITH_REFUSAL.format(slug=self.slug, refusal=self.refusal)
        return _DRIVER_START_BUSY_SUMMARY.format(slug=self.slug)


_LANE_CROSSING_SUMMARY_TEMPLATE = (
    "LaneCrossingRefused: {slug} is held in the {held_lane} lane and cannot be entered from the "
    "{requested_lane} machine; {sanctioned_path}"
)


class LaneCrossingRefusedErrorPayload(OperationErrorPayload):
    """Structured lane-crossing refusal payload."""

    slug: str
    held_lane: str
    requested_lane: str
    sanctioned_path: str


class LaneCrossingRefused(OperationFailure):
    """Lifecycle entry refused because the caller holds the slug in the other SDLC lane.

    A session that holds a todo in the prepare lane is never adopted into the work
    lane, and the reverse. The refusal reads the object (who holds the slug, in which
    lane) and names its door: ``sanctioned_path`` states how the todo changes hands
    through the lifecycle runner instead.
    """

    error_kind = "lane_crossing_refused"

    def __init__(self, *, slug: str, held_lane: str, requested_lane: str, sanctioned_path: str) -> None:
        self.slug = slug
        self.held_lane = held_lane
        self.requested_lane = requested_lane
        self.sanctioned_path = sanctioned_path
        self.work_feedback = _LANE_CROSSING_WORK_FEEDBACK.format(
            held_lane=held_lane,
            requested_lane=requested_lane,
            sanctioned_path=sanctioned_path,
        )
        super().__init__(slug)

    def to_error_payload(self) -> LaneCrossingRefusedErrorPayload:
        return {
            "kind": self.error_kind,
            "slug": self.slug,
            "held_lane": self.held_lane,
            "requested_lane": self.requested_lane,
            "sanctioned_path": self.sanctioned_path,
        }

    def summary(self) -> str:
        return _LANE_CROSSING_SUMMARY_TEMPLATE.format(
            slug=self.slug,
            held_lane=self.held_lane,
            requested_lane=self.requested_lane,
            sanctioned_path=self.sanctioned_path,
        )
