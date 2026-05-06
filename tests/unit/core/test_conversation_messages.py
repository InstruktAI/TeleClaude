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


# ── Classifier branch coverage ──────────────────────────────────────────────
# One test per decision path inside classify_linked_direct_conversation_output.


def _frame(content: str) -> str:
    return format_linked_output_message(
        sender_label="Peer",
        sender_session_id="peer-001",
        sender_computer="remote",
        content=content,
    )


@pytest.mark.unit
def test_classify_returns_not_linked_output_for_unframed_text() -> None:
    """Raw text without a [TeleClaude Linked output ...] wrapper is rejected upfront."""
    classification = classify_linked_direct_conversation_output("just some raw text")

    assert classification.emit is False
    assert classification.reason == "not_linked_output"
    assert classification.payload == ""


@pytest.mark.unit
def test_classify_suppresses_idle_pattern() -> None:
    """Short payloads matching the idle/standby regex are non-actionable status."""
    classification = classify_linked_direct_conversation_output(_frame("Idle, standing by."))

    assert classification.emit is False
    assert classification.reason == "idle_or_noop"


@pytest.mark.unit
def test_classify_suppresses_status_narration_pattern() -> None:
    """Self-referential status narration is not actionable for the peer."""
    classification = classify_linked_direct_conversation_output(_frame("Looking into it."))

    assert classification.emit is False
    assert classification.reason == "status_narration_only"


@pytest.mark.unit
def test_classify_suppresses_empty_payload() -> None:
    """A wrapper with no payload body cannot drive any peer action."""
    classification = classify_linked_direct_conversation_output(_frame(""))

    assert classification.emit is False
    assert classification.reason == "empty_payload"


@pytest.mark.unit
def test_classify_suppresses_non_actionable_short_text() -> None:
    """Short payloads without a meaningful hint and no recognized pattern fall through to non_actionable."""
    classification = classify_linked_direct_conversation_output(_frame("yes done"))

    assert classification.emit is False
    assert classification.reason == "non_actionable"
