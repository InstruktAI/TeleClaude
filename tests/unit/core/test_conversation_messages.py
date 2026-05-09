"""Tests for the canonical identity-header helper and bridge matchers."""

from __future__ import annotations

import pytest

from teleclaude.core.conversation_messages import (
    format_identity_header,
    format_peer_header,
    is_conversation_bridge_message,
    is_orchestrator_dispatch_message,
)


@pytest.mark.unit
def test_format_identity_header_includes_role_session_and_computer() -> None:
    """Identity header carries role + full session UUID + computer when no category is given."""
    header = format_identity_header(
        role="Orchestrator",
        session_id="7cbd6584-802c-46da-9820-bdfcf075cf0f",
        computer="local",
    )
    assert header == "[Orchestrator (7cbd6584-802c-46da-9820-bdfcf075cf0f) on local]"


@pytest.mark.unit
def test_format_identity_header_with_category_renders_role_dash_category() -> None:
    """When a category is supplied, it appears between the role and the identity tuple."""
    header = format_identity_header(
        role="TeleClaude",
        category="Peer",
        session_id="sess-uuid",
        computer="host",
    )
    assert header == "[TeleClaude - Peer (sess-uuid) on host]"


@pytest.mark.unit
def test_format_peer_header_uses_canonical_peer_category() -> None:
    """The peer-header helper produces the bracket every bridge message starts with."""
    header = format_peer_header(sender_session_id="sess-uuid", sender_computer="host")
    assert header == "[TeleClaude - Peer (sess-uuid) on host]"


@pytest.mark.unit
def test_is_conversation_bridge_message_recognizes_peer_prefix() -> None:
    """The Peer category is the only outer header bridge messages carry."""
    assert is_conversation_bridge_message("[TeleClaude - Peer (s) on h]\n\nbody")


@pytest.mark.unit
def test_is_conversation_bridge_message_rejects_non_bridge_brackets() -> None:
    """Orchestrator dispatch and bare TeleClaude prefix are not bridge messages."""
    assert not is_conversation_bridge_message("[Orchestrator (orch) on local]\n\nDispatch body")
    assert not is_conversation_bridge_message("[TeleClaude Checkpoint] - heartbeat")
    assert not is_conversation_bridge_message("plain user prompt")


@pytest.mark.unit
def test_is_orchestrator_dispatch_message_recognizes_orchestrator_bracket() -> None:
    assert is_orchestrator_dispatch_message("[Orchestrator (orch-uuid) on local]\n\nbody")


@pytest.mark.unit
def test_is_orchestrator_dispatch_message_rejects_other_roles_and_plain_text() -> None:
    """Only the Orchestrator role passes — TeleClaude bridges and plain text don't."""
    assert not is_orchestrator_dispatch_message("[TeleClaude - Peer (s) on h]\n\nbody")
    assert not is_orchestrator_dispatch_message("Dispatch reason: upstream-changed")
