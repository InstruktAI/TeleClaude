"""Characterization tests for teleclaude.core.integration.authorization."""

from __future__ import annotations

import pytest

from teleclaude.core.integration.authorization import (
    CutoverResolution,
    IntegrationAuthorizationError,
    IntegratorCutoverControls,
    require_integrator_owner,
    resolve_cutover_mode,
)

# ---------------------------------------------------------------------------
# resolve_cutover_mode
# ---------------------------------------------------------------------------


def test_resolve_cutover_mode_shadow_requested_returns_shadow():
    controls = IntegratorCutoverControls(enabled=True, parity_evidence_accepted=True)
    result = resolve_cutover_mode(requested_shadow_mode=True, controls=controls)
    assert result.shadow_mode is True
    assert result.rollback_required is False


def test_resolve_cutover_mode_cutover_disabled_stays_shadow():
    controls = IntegratorCutoverControls(enabled=False)
    result = resolve_cutover_mode(requested_shadow_mode=False, controls=controls)
    assert result.shadow_mode is True
    assert result.rollback_required is False


def test_resolve_cutover_mode_parity_accepted_enables_enforced():
    controls = IntegratorCutoverControls(enabled=True, parity_evidence_accepted=True)
    result = resolve_cutover_mode(requested_shadow_mode=False, controls=controls)
    assert result.shadow_mode is False
    assert result.rollback_required is False
    assert result.reason is None


def test_resolve_cutover_mode_incomplete_parity_with_rollback_returns_shadow():
    controls = IntegratorCutoverControls(
        enabled=True, parity_evidence_accepted=False, rollback_on_incomplete_parity=True
    )
    result = resolve_cutover_mode(requested_shadow_mode=False, controls=controls)
    assert result.shadow_mode is True
    assert result.rollback_required is True


def test_resolve_cutover_mode_incomplete_parity_no_rollback_raises():
    controls = IntegratorCutoverControls(
        enabled=True, parity_evidence_accepted=False, rollback_on_incomplete_parity=False
    )
    with pytest.raises(IntegrationAuthorizationError):
        resolve_cutover_mode(requested_shadow_mode=False, controls=controls)


def test_cutover_resolution_is_frozen():
    result = CutoverResolution(shadow_mode=True, rollback_required=False, reason=None)
    with pytest.raises(AttributeError):
        result.shadow_mode = False  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# require_integrator_owner
# ---------------------------------------------------------------------------


def test_require_integrator_owner_passes_for_authorized_owner():
    require_integrator_owner(
        owner_session_id="integrator-abc",
        is_integrator_owner=lambda sid: sid == "integrator-abc",
        action="canonical-main push",
    )


def test_require_integrator_owner_raises_for_unauthorized_owner():
    with pytest.raises(IntegrationAuthorizationError):
        require_integrator_owner(
            owner_session_id="worker-xyz",
            is_integrator_owner=lambda sid: sid.startswith("integrator-"),
            action="canonical-main push",
        )


def test_require_integrator_owner_error_contains_session_id():
    with pytest.raises(IntegrationAuthorizationError) as exc_info:
        require_integrator_owner(
            owner_session_id="non-integrator",
            is_integrator_owner=lambda _: False,
            action="push",
        )
    # Session ID is execution-significant diagnostic data in the error
    assert "non-integrator" in str(exc_info.value)
