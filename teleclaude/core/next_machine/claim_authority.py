"""Shared claim-ownership classification for workflow mutations."""

from __future__ import annotations

from enum import StrEnum


class ClaimOwnership(StrEnum):
    OWNS_BINDING = "owns_binding"
    OWNS_CLAIM = "owns_claim"
    UNCLAIMED = "unclaimed"
    CONFLICTING_BINDING = "conflicting_binding"
    FOREIGN_CLAIM = "foreign_claim"


def classify_claim_ownership(
    *,
    slug: str,
    caller_working_slug: str | None,
    caller_session_id: str | None,
    live_claimant: str | None,
) -> ClaimOwnership:
    if caller_working_slug:
        if caller_working_slug == slug:
            return ClaimOwnership.OWNS_BINDING
        return ClaimOwnership.CONFLICTING_BINDING

    if caller_session_id and live_claimant == caller_session_id:
        return ClaimOwnership.OWNS_CLAIM

    if live_claimant:
        return ClaimOwnership.FOREIGN_CLAIM

    return ClaimOwnership.UNCLAIMED


__all__ = ["ClaimOwnership", "classify_claim_ownership"]
