"""Tests for the canonical identity-header helper and bridge matchers."""

from __future__ import annotations

import pytest

from teleclaude.core.conversation_messages import (
    format_identity_header,
    format_orchestrator_header,
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
        category="Linked output",
        session_id="sess-uuid",
        computer="host",
    )
    assert header == "[TeleClaude - Linked output (sess-uuid) on host]"


@pytest.mark.unit
def test_format_orchestrator_header_emits_canonical_orchestrator_bracket() -> None:
    header = format_orchestrator_header(
        orchestrator_session_id="orch-uuid",
        orchestrator_computer="local",
    )
    assert header == "[Orchestrator (orch-uuid) on local]"


@pytest.mark.unit
def test_is_conversation_bridge_message_recognizes_each_category() -> None:
    """Every TeleClaude category that drives receiver-side dispatch is recognized."""
    assert is_conversation_bridge_message("[TeleClaude - Linked output (s) on h]\n\nbody")
    assert is_conversation_bridge_message("[TeleClaude - Conversation update (s) on h]\n\nbody")
    assert is_conversation_bridge_message("[TeleClaude - Direct Conversation (s) on h]\n\nbody")
    assert is_conversation_bridge_message("[TeleClaude - Human in the Loop (s) on h]\n\nbody")


@pytest.mark.unit
def test_is_conversation_bridge_message_rejects_non_bridge_brackets() -> None:
    """Orchestrator dispatch and bare TeleClaude prefix are NOT bridge messages —
    bridge classification gates the deliver-inbound system-skip and the
    last_conversation_injected_at write, so it must be precise."""
    assert not is_conversation_bridge_message("[Orchestrator (orch) on local]\n\nDispatch body")
    assert not is_conversation_bridge_message("[TeleClaude Checkpoint] - heartbeat")
    assert not is_conversation_bridge_message("plain user prompt")


@pytest.mark.unit
def test_is_orchestrator_dispatch_message_recognizes_orchestrator_bracket() -> None:
    assert is_orchestrator_dispatch_message("[Orchestrator (orch-uuid) on local]\n\nbody")


@pytest.mark.unit
def test_is_orchestrator_dispatch_message_rejects_other_roles_and_plain_text() -> None:
    """Only the Orchestrator role passes — TeleClaude bridges and plain text don't."""
    assert not is_orchestrator_dispatch_message("[TeleClaude - Linked output (s) on h]\n\nbody")
    assert not is_orchestrator_dispatch_message("Dispatch reason: upstream-changed")
