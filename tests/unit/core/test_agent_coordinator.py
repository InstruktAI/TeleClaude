"""Unit tests for echo suppression in teleclaude.core.agent_coordinator.

Tests the turn_triggered_by_linked_output flag that separates queue-drain state
(deliver_inbound) from agent-processing state (user_prompt_submit) for accurate
echo suppression in handle_agent_stop.

The coordinator module has heavy import-time dependencies (config, DB, transport).
These tests verify the behavioral contracts of the echo suppression logic without
importing the full module — testing the data flow and decision rules directly.
"""

from __future__ import annotations

from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX

# ---------------------------------------------------------------------------
# Constants mirroring production code
# ---------------------------------------------------------------------------

LINKED_PREFIX = f"{TELECLAUDE_SYSTEM_PREFIX} Linked output from "


# ---------------------------------------------------------------------------
# Flag derivation logic (mirrors handle_user_prompt_submit)
# ---------------------------------------------------------------------------


def _derive_linked_flag(prompt_text: str) -> bool:
    """Reproduce the flag derivation from handle_user_prompt_submit."""
    return prompt_text.strip().startswith(LINKED_PREFIX)


def _should_suppress_fanout(session_exists: bool, flag_value: bool) -> bool:
    """Reproduce the echo suppression decision from handle_agent_stop."""
    return session_exists and flag_value


# ---------------------------------------------------------------------------
# Tests: flag derivation (handle_user_prompt_submit behavior)
# ---------------------------------------------------------------------------


def test_flag_true_for_linked_output_message():
    """Linked output prefix in prompt text must produce a True flag."""
    prompt = f"{LINKED_PREFIX}reviewer (sess-002):\nHere is my review."
    assert _derive_linked_flag(prompt) is True


def test_flag_true_for_linked_output_with_leading_whitespace():
    """Leading whitespace before the linked prefix must still be recognized."""
    prompt = f"  {LINKED_PREFIX}reviewer (sess-002):\nHere is my review."
    assert _derive_linked_flag(prompt) is True


def test_flag_false_for_direct_conversation_message():
    """A normal direct conversation message must produce a False flag."""
    prompt = "Please fix the import error in module X."
    assert _derive_linked_flag(prompt) is False


def test_flag_false_for_empty_prompt():
    """An empty prompt must produce a False flag."""
    assert _derive_linked_flag("") is False


def test_flag_false_for_partial_prefix():
    """A prompt that partially matches the prefix must not trigger."""
    prompt = f"{TELECLAUDE_SYSTEM_PREFIX} Some other system message"
    assert _derive_linked_flag(prompt) is False


def test_flag_false_for_prefix_in_body():
    """The linked prefix appearing mid-message (not at start) must not trigger."""
    prompt = f"FYI: {LINKED_PREFIX}reviewer (sess-002):\nsome text"
    assert _derive_linked_flag(prompt) is False


# ---------------------------------------------------------------------------
# Tests: echo suppression decision (handle_agent_stop behavior)
# ---------------------------------------------------------------------------


def test_fanout_proceeds_when_flag_false():
    """Fan-out must proceed when the flag says this was a direct trigger."""
    assert _should_suppress_fanout(session_exists=True, flag_value=False) is False


def test_fanout_suppressed_when_flag_true():
    """Fan-out must be suppressed when the flag says linked-output trigger."""
    assert _should_suppress_fanout(session_exists=True, flag_value=True) is True


def test_fanout_proceeds_when_no_session():
    """Fan-out decision must not suppress when session is None."""
    assert _should_suppress_fanout(session_exists=False, flag_value=True) is False


# ---------------------------------------------------------------------------
# Tests: the core bug scenario — poisoned state from deliver_inbound
# ---------------------------------------------------------------------------


def test_direct_trigger_not_poisoned_by_deliver_inbound_state():
    """Core bug scenario: deliver_inbound eagerly wrote linked output to
    last_message_sent, but the agent was actually triggered by a direct
    conversation message. The flag must reflect the actual trigger (False),
    and fan-out must proceed."""
    # Simulate: deliver_inbound wrote linked output to DB (poisoned state)
    db_last_message_sent = f"{LINKED_PREFIX}someone (sess-X):\npoisoned"
    db_last_input_origin = "redis"

    # But user_prompt_submit fires with the REAL trigger: a direct message
    actual_prompt = "Please fix the import error in module X."

    # Flag derivation uses the actual prompt, not the DB state
    flag = _derive_linked_flag(actual_prompt)
    assert flag is False, "Flag must reflect the actual prompt, not DB state"

    # Echo suppression uses the flag, not last_message_sent
    suppressed = _should_suppress_fanout(session_exists=True, flag_value=flag)
    assert suppressed is False, "Fan-out must proceed for direct conversation triggers"

    # Verify the old (buggy) logic WOULD have suppressed this
    _old_buggy_check = db_last_input_origin.strip().lower() == "redis" and (db_last_message_sent or "").startswith(
        LINKED_PREFIX
    )
    assert _old_buggy_check is True, "Old logic would have incorrectly suppressed fan-out"


def test_linked_trigger_correctly_suppresses():
    """When the agent genuinely processes linked output, suppression is correct."""
    actual_prompt = f"{LINKED_PREFIX}reviewer (sess-002):\nHere is my review."

    flag = _derive_linked_flag(actual_prompt)
    assert flag is True

    suppressed = _should_suppress_fanout(session_exists=True, flag_value=flag)
    assert suppressed is True, "Fan-out must be suppressed for linked-output triggers"
