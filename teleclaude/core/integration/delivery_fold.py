"""Delivered-snippet fold and fail-closed marker gate for the delivery chokepoint.

`PUSH_SUCCEEDED` is the universal delivery chokepoint: every committed path
— clean merge, conflict resolution, and crash/resume — converges here before final
publication. These helpers re-assert the idempotent fold and gate the root state
on a clean tree, so a delivered slug never reaches `origin/main`
carrying live markers that trip the platform liveness guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.marker_reconciliation import (
    MarkerMoment,
    MarkerReceipt,
    reconcile_lifecycle_markers,
)
from teleclaude.docs_reconcile import (
    MarkerDivergence,
    ResidualMarkerError,
    assert_no_residual_markers,
    find_marker_divergence,
)


@dataclass(frozen=True)
class DeliveredMarkerRecoveryFault:
    """One delivered slug whose terminal reconciliation could not complete."""

    receipt: MarkerReceipt
    divergences: tuple[MarkerDivergence, ...]


@dataclass(frozen=True)
class DeliveredMarkerRecoveryResult:
    """Applied recovery receipts and retained faults from one root scan."""

    applied_receipts: tuple[MarkerReceipt, ...]
    faults: tuple[DeliveredMarkerRecoveryFault, ...]


def reassert_delivered_fold(reconciliation_root: Path, slug: str) -> tuple[bool, MarkerReceipt, str | None]:
    """Re-run the idempotent delivered-snippet fold over one reconciliation root.

    Returns ``(staged_changed, receipt, error)``. ``error`` is a human-readable
    message when the fold fails closed (residual marker or filesystem error) and the
    caller must suppress the push; it is ``None`` on success. ``staged_changed`` is
    ``True`` when the fold rewrote snippets and the caller must stage the worktree
    before the push. A failure here is surfaced so the tree never reaches main.
    """
    receipt = reconcile_lifecycle_markers(reconciliation_root, slug, MarkerMoment.DELIVER)
    if receipt.succeeded:
        return receipt.outcome.value == "applied", receipt, None
    return False, receipt, f"Delivered-snippet fold failed for {slug}; refusing to push: {receipt.reason}"


def recover_delivered_marker_divergence(
    reconciliation_root: Path,
    delivered_slugs: set[str],
) -> DeliveredMarkerRecoveryResult:
    """Repair only delivered-slug marker divergence found at an idle integration entry."""
    delivered_statuses = {slug: TodoStatus.DELIVERED.value for slug in delivered_slugs}
    findings = find_marker_divergence(reconciliation_root, delivered_statuses)
    findings_by_slug: dict[str, list[MarkerDivergence]] = {}
    for finding in findings:
        findings_by_slug.setdefault(finding.slug, []).append(finding)
    applied_receipts: list[MarkerReceipt] = []
    faults: list[DeliveredMarkerRecoveryFault] = []
    for slug in sorted(findings_by_slug):
        receipt = reconcile_lifecycle_markers(reconciliation_root, slug, MarkerMoment.DELIVER)
        if receipt.succeeded:
            if receipt.commit is not None:
                applied_receipts.append(receipt)
        else:
            faults.append(
                DeliveredMarkerRecoveryFault(
                    receipt=receipt,
                    divergences=tuple(findings_by_slug[slug]),
                )
            )
    return DeliveredMarkerRecoveryResult(
        applied_receipts=tuple(applied_receipts),
        faults=tuple(faults),
    )


def assert_clean_before_push(reconciliation_root: Path, slug: str) -> str | None:
    """Independent fail-closed gate immediately before the push.

    Returns a human-readable message when a delivered slug's markers survived the
    fold (so the caller must suppress the push), or ``None`` when the tree is clean.
    This runs even if a future fold path regresses and leaves markers behind.
    """
    try:
        assert_no_residual_markers(reconciliation_root, slug)
    except (ResidualMarkerError, OSError) as exc:
        return f"Residual '{slug}' markers survived the delivery fold; refusing to push: {exc}"
    return None
