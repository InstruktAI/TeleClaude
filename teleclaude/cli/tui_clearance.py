"""Command clearance for the TUI's aggregate bootstrap request."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.api_models import TuiBootstrapErrorDTO, TuiBootstrapPillar
from teleclaude.cli.clearance import ClearanceScope, clearance_scope_refusal
from teleclaude.cli.session_auth import ResolvedCliIdentity

_PILLAR_VERBS: dict[TuiBootstrapPillar, str | None] = {
    "computers": "computers list",
    "projects": "projects list",
    "sessions": "sessions list",
    "availability": "agents availability",
    "jobs": None,
    "settings": None,
    "chiptunes": None,
    "ownership": None,
}


@dataclass(frozen=True)
class TuiBootstrapClearance:
    """Pillars the caller may request and their combined verb scope."""

    allowed: list[TuiBootstrapPillar]
    denied: list[TuiBootstrapErrorDTO]
    request_scope: ClearanceScope


def clear_tui_bootstrap_pillars(
    requested: list[TuiBootstrapPillar], identity: ResolvedCliIdentity | None
) -> TuiBootstrapClearance:
    """Clear each bootstrap pillar independently before the aggregate request."""
    allowed: list[TuiBootstrapPillar] = []
    denied: list[TuiBootstrapErrorDTO] = []
    allowed_verbs: list[str] = []
    for pillar in requested:
        command_path = _PILLAR_VERBS[pillar]
        scope = ClearanceScope.verb(command_path) if command_path else ClearanceScope.ungoverned()
        refusal = clearance_scope_refusal(scope, identity)
        if refusal is None:
            allowed.append(pillar)
            if command_path is not None:
                allowed_verbs.append(command_path)
        else:
            denied.append(TuiBootstrapErrorDTO(pillar=pillar, message=refusal, retryable=False))
    request_scope = ClearanceScope.verbs(allowed_verbs) if allowed_verbs else ClearanceScope.ungoverned()
    return TuiBootstrapClearance(allowed=allowed, denied=denied, request_scope=request_scope)
