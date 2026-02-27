"""Authorization and cutover controls for canonical-main integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class IntegrationAuthorizationError(RuntimeError):
    """Raised when a caller is not allowed to perform canonical-main actions."""


@dataclass(frozen=True)
class IntegratorCutoverControls:
    """Control plane for transitioning from shadow mode to enforced integration."""

    enabled: bool = False
    parity_evidence_accepted: bool = False
    rollback_on_incomplete_parity: bool = True


@dataclass(frozen=True)
class CutoverResolution:
    """Resolved runtime mode derived from requested mode and cutover controls."""

    shadow_mode: bool
    rollback_required: bool
    reason: str | None


def resolve_cutover_mode(*, requested_shadow_mode: bool, controls: IntegratorCutoverControls) -> CutoverResolution:
    """Resolve effective mode while enforcing parity-evidence cutover policy."""
    if requested_shadow_mode:
        return CutoverResolution(
            shadow_mode=True,
            rollback_required=False,
            reason="shadow mode explicitly requested",
        )

    if not controls.enabled:
        return CutoverResolution(
            shadow_mode=True,
            rollback_required=False,
            reason="cutover disabled: remaining in shadow mode",
        )

    if controls.parity_evidence_accepted:
        return CutoverResolution(
            shadow_mode=False,
            rollback_required=False,
            reason=None,
        )

    if controls.rollback_on_incomplete_parity:
        return CutoverResolution(
            shadow_mode=True,
            rollback_required=True,
            reason="parity evidence incomplete: rollback to shadow mode",
        )

    raise IntegrationAuthorizationError(
        "cutover is enabled but parity evidence is incomplete; "
        "accept parity evidence or enable rollback_on_incomplete_parity"
    )


def require_integrator_owner(
    *,
    owner_session_id: str,
    is_integrator_owner: Callable[[str], bool],
    action: str,
) -> None:
    """Fail fast when a non-integrator attempts canonical-main actions."""
    if is_integrator_owner(owner_session_id):
        return
    raise IntegrationAuthorizationError(
        f"{action} requires integrator ownership; owner_session_id={owner_session_id!r} is not authorized"
    )
