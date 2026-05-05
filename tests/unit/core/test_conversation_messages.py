from __future__ import annotations

import pytest

from teleclaude.core.conversation_messages import (
    classify_linked_direct_conversation_output,
    format_linked_output_message,
    parse_linked_output_message,
)


@pytest.mark.unit
def test_classify_linked_direct_output_uses_wrapped_payload_not_wrapper_text() -> None:
    message = format_linked_output_message(
        sender_label="Peer",
        sender_session_id="peer-001",
        sender_computer="remote",
        content="Thanks.",
    )

    classification = classify_linked_direct_conversation_output(message)

    assert classification.emit is False
    assert classification.reason == "acknowledgment_only"
    assert classification.preview == "Thanks."


@pytest.mark.unit
def test_classify_linked_direct_output_allows_short_diagnostic_payload() -> None:
    message = format_linked_output_message(
        sender_label="Peer",
        sender_session_id="peer-001",
        sender_computer="remote",
        content="Missing cursor advance on suppressed output.",
    )

    classification = classify_linked_direct_conversation_output(message)

    assert classification.emit is True
    assert classification.reason == "meaningful"


@pytest.mark.unit
def test_parse_linked_output_message_extracts_sender_metadata_and_payload() -> None:
    message = format_linked_output_message(
        sender_label="Peer Session",
        sender_session_id="peer-001",
        sender_computer="remote",
        content="Need review on the linked replay cursor.",
    )

    parsed = parse_linked_output_message(message)

    assert parsed is not None
    assert parsed.sender_label == "Peer Session"
    assert parsed.sender_session_id == "peer-001"
    assert parsed.sender_computer == "remote"
    assert parsed.payload == "Need review on the linked replay cursor."
