"""Response helpers for session API routes."""

from __future__ import annotations

from teleclaude.api_models import SendMessageResponseDTO

_RESPONSE_STATUS_ERROR = "error"
_RESPONSE_MODE_DIRECT = "direct"

# Refusal copy for a direct-link request that would give an endpoint a second
# concurrent peer. It names the endpoint's existing peer so the requester can
# act on the refusal instead of retrying blind.
_EXCLUSIVE_DIRECT_LINK_TEMPLATE = (
    "Session {endpoint_session_id} is already in a direct conversation with "
    "{peer_label} ({peer_session_id}). Direct conversation is exclusive to two peers, "
    "so no second link is created and that conversation is untouched. "
    "Wait for it to close, or reach this session another way."
)


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


def exclusive_direct_link_response(
    *,
    link_id: str,
    endpoint_session_id: str,
    peer_session_id: str,
    peer_name: str | None,
) -> SendMessageResponseDTO:
    """Return the refusal for a direct link that would give an endpoint a second peer."""
    return SendMessageResponseDTO(
        status=_RESPONSE_STATUS_ERROR,
        mode=_RESPONSE_MODE_DIRECT,
        link_id=link_id,
        message=_EXCLUSIVE_DIRECT_LINK_TEMPLATE.format(
            endpoint_session_id=endpoint_session_id,
            peer_label=peer_name or peer_session_id,
            peer_session_id=peer_session_id,
        ),
    )
