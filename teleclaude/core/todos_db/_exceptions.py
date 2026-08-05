"""Typed exceptions for todo database contract refusals."""

from __future__ import annotations

from typing_extensions import TypedDict

from teleclaude.docs_reconcile import BlockingSnippet


class OperationErrorPayload(TypedDict):
    """Structured operation failure payload contract."""

    kind: str


class RemoveRefusalSnippetPayload(TypedDict):
    """Serialized snippet blocker payload for remove refusals."""

    path: str
    slug_role: str
    live_deliverer_count: int
    other_removed_deliverers: list[str]


class RemoveRefusalErrorPayload(OperationErrorPayload):
    """Structured remove-refusal operation payload."""

    blocking_snippets: list[RemoveRefusalSnippetPayload]


class ClaimConflictErrorPayload(OperationErrorPayload):
    """Structured driver-start conflict payload."""

    slug: str
    holder: str | None


class OperationFailure(Exception):
    """Base class for operation failures with structured API payloads."""

    error_kind: str

    def to_error_payload(self) -> OperationErrorPayload:
        """Return the machine-readable operation error payload."""
        raise NotImplementedError

    def summary(self) -> str:
        """Return a short human-readable error summary."""
        return f"{type(self).__name__}: {self}"


class RemoveRefused(OperationFailure):
    """Soft-remove refused because it would orphan snippet deliverers."""

    error_kind = "remove_refused_orphan"

    def __init__(self, *, slug: str, blocking_snippets: list[BlockingSnippet]) -> None:
        self.slug = slug
        self.blocking_snippets = blocking_snippets
        super().__init__(slug)

    def to_error_payload(self) -> RemoveRefusalErrorPayload:
        return {
            "kind": self.error_kind,
            "blocking_snippets": [
                {
                    "path": snippet.path,
                    "slug_role": snippet.slug_role,
                    "live_deliverer_count": snippet.live_deliverer_count,
                    "other_removed_deliverers": list(snippet.other_removed_deliverers),
                }
                for snippet in self.blocking_snippets
            ],
        }

    def summary(self) -> str:
        count = len(self.blocking_snippets)
        return f"RemoveRefused: {count} snippet(s) would be orphaned"


class ReviewerConflictErrorPayload(OperationErrorPayload):
    """Structured reviewer-conflict payload for any reviewer-conflict subject.

    Applies to every slug-bound reviewer (``/next-review-build``,
    ``/next-review-plan``, ``/next-review-architecture``) as well as the
    slugless commit-review subject (``/next-review-commits``).
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

    Commit review's subject is ``(project, initiating driver, command)`` —
    there is no todo slug to key on instead. A web-origin caller's identity
    (``web:<uuid>``) is never persisted as ``initiator_session_id`` (it is not a
    real session row; see ``sessions_actions_routes._prepare_run_session``), so
    such a launch cannot be looked up against a prior holder. Admitting it
    silently would bypass dedup entirely for that origin, which is the gap R1
    requires closed with no escape hatch — so the create door refuses rather
    than starting an unkeyed reviewer. This is a sibling member of the same
    ``OperationFailure`` family as ``ReviewerConflict``, not a widening of it:
    unlike a real conflict, there is no live holder to name.
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

    def __init__(self, *, slug: str, holder: str | None) -> None:
        self.slug = slug
        self.holder = holder
        super().__init__(slug)

    def to_error_payload(self) -> ClaimConflictErrorPayload:
        return {"kind": self.error_kind, "slug": self.slug, "holder": self.holder}

    def summary(self) -> str:
        if self.holder:
            return f"ClaimConflict: {self.slug} is already driven by session {self.holder}"
        return f"ClaimConflict: {self.slug} is already driven"
