"""Delivered-snippet fold and fail-closed marker gate for the delivery chokepoint.

`DELIVERY_BOOKKEEPING` is the universal delivery chokepoint: every committed path
— clean merge, conflict resolution, and crash/resume — converges here before the
push, but only the clean-merge branch folds the delivered slug's pending doc
snippets eagerly (in `_do_merge`). These helpers let the bookkeeping step re-assert
the idempotent fold and gate the push on a clean tree, so a delivered slug never
reaches `origin/main` carrying live markers that trip the platform liveness guard.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.next_machine.marker_reconciliation import MarkerMoment, reconcile_lifecycle_markers
from teleclaude.docs_reconcile import ResidualMarkerError, assert_no_residual_markers


def reassert_delivered_fold(integration_wt: Path, slug: str) -> tuple[bool, str | None]:
    """Re-run the idempotent delivered-snippet fold over the integration worktree.

    Returns ``(staged_changed, error)``. ``error`` is a human-readable message when
    the fold fails closed (residual marker or filesystem error) and the caller must
    suppress the push; it is ``None`` on success. ``staged_changed`` is ``True`` when
    the fold rewrote snippets and the caller must stage the worktree before the push.
    Unlike the eager clean-merge fold — which swallows reconcile errors to never fail
    an already-clean merge — a failure here is surfaced so the tree never reaches main.
    """
    receipt = reconcile_lifecycle_markers(integration_wt, slug, MarkerMoment.DELIVER)
    if receipt.succeeded:
        return receipt.outcome.value == "applied", None
    return False, f"Delivered-snippet fold failed for {slug}; refusing to push: {receipt.reason}"


def assert_clean_before_push(integration_wt: Path, slug: str) -> str | None:
    """Independent fail-closed gate immediately before the push.

    Returns a human-readable message when a delivered slug's markers survived the
    fold (so the caller must suppress the push), or ``None`` when the tree is clean.
    This runs even if a future fold path regresses and leaves markers behind.
    """
    try:
        assert_no_residual_markers(integration_wt, slug)
    except (ResidualMarkerError, OSError) as exc:
        return f"Residual '{slug}' markers survived the delivery fold; refusing to push: {exc}"
    return None
