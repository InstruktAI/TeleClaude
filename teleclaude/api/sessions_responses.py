"""Response helpers for session API routes."""

from __future__ import annotations

from teleclaude.api_models import SendMessageResponseDTO


def active_direct_link_response(
    link_id: str,
    *,
    already_active: bool,
) -> SendMessageResponseDTO:
    """Return the standard response for blocked direct-link sends."""
    return SendMessageResponseDTO(
        status="error",
        mode="direct",
        link_id=link_id,
        message=(
            (
                "A direct link is already active with this peer. "
                if already_active
                else "A direct link is active with this peer. "
            )
            + (
                "We agreed not to use send during direct conversation "
                "as it obfuscates the exchange from the observer. "
                "Your turn-complete output is automatically shared — just talk."
            )
        ),
    )
