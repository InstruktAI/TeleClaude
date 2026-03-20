# guard: no-companion
"""Test specifications for FR-6: Documentation deliverables.

Four architecture documents must be updated to reflect the IMPLEMENTED changes:
1. Command classification design doc — correct classification errors, full endpoint-to-mode table
2. Operation receipts design doc — generalized to cover todo_create and todo_prepare kinds
3. API server design doc — command classification table showing endpoint-to-mode mapping
4. Redis transport design doc — section on response_mode-driven caller behavior

Tests assert content that only exists after the implementation updates these docs.
Pre-existing content is not sufficient — these check for post-implementation specifics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_DOCS_ROOT = Path(__file__).resolve().parents[3] / "docs" / "project" / "design" / "architecture"


class TestCommandClassificationDocUpdated:
    """Command classification doc corrected and reflects implemented constructor pattern."""

    @pytest.mark.unit
    def test_command_classification_documents_construction_time_enforcement(self) -> None:
        """The doc describes the construction-time invariant for FIRE_AND_FORGET
        commands requiring completion_event — this is a new behavioral contract
        that must be documented post-implementation."""
        doc = _DOCS_ROOT / "command-classification.md"
        content = doc.read_text(encoding="utf-8")
        # The construction-time enforcement of FF+completion_event is a new invariant.
        # The doc must describe that FF without completion_event raises at construction.
        assert "construction" in content.lower() or "instantiation" in content.lower(), (
            "command-classification doc must document construction-time enforcement "
            "of FIRE_AND_FORGET+completion_event invariant"
        )

    @pytest.mark.unit
    def test_command_classification_corrects_restart_agent_classification(self) -> None:
        """RestartAgentCommand must be classified as FIRE_AND_FORGET, not IMMEDIATE.

        The input audit confirms agent-restart already returns 202 and needs an event.
        The pre-implementation doc incorrectly lists RestartAgentCommand under IMMEDIATE.
        """
        doc = _DOCS_ROOT / "command-classification.md"
        content = doc.read_text(encoding="utf-8")

        # Find the IMMEDIATE section and check that RestartAgentCommand is NOT in it.
        # The doc currently has RestartAgentCommand listed in the IMMEDIATE section.
        # After fix, it must be under FIRE_AND_FORGET instead.
        sections = content.split("##")
        for section in sections:
            section_lower = section.lower()
            if "immediate" in section_lower and "fire" not in section_lower:
                # This is the IMMEDIATE section — RestartAgentCommand must not be here
                assert "RestartAgentCommand" not in section, (
                    "RestartAgentCommand is still listed in the IMMEDIATE section. "
                    "Must be moved to FIRE_AND_FORGET per input audit."
                )


class TestOperationReceiptsDocGeneralized:
    """Operation receipts doc generalized beyond todo_work/integrate to include new kinds."""

    @pytest.mark.unit
    def test_operation_receipts_covers_todo_create_kind(self) -> None:
        """The doc lists todo_create as a supported operation kind."""
        doc = _DOCS_ROOT / "operation-receipts.md"
        content = doc.read_text(encoding="utf-8")
        assert "todo_create" in content, "operation-receipts doc must document the todo_create operation kind"

    @pytest.mark.unit
    def test_operation_receipts_covers_todo_prepare_kind(self) -> None:
        """The doc lists todo_prepare as a supported operation kind."""
        doc = _DOCS_ROOT / "operation-receipts.md"
        content = doc.read_text(encoding="utf-8")
        assert "todo_prepare" in content, "operation-receipts doc must document the todo_prepare operation kind"


class TestApiServerDocClassificationTable:
    """API server doc includes endpoint-to-response-mode mapping table."""

    @pytest.mark.unit
    def test_api_server_classifies_message_endpoint_as_immediate(self) -> None:
        """The API server doc classifies the message endpoint as IMMEDIATE (not FIRE_AND_FORGET).

        The input audit marks POST /sessions/{id}/message as 'already correct' with 200 status.
        After implementation, the doc must reflect this as IMMEDIATE, correcting any pre-existing
        FIRE_AND_FORGET classification.
        """
        doc = _DOCS_ROOT / "api-server.md"
        content = doc.read_text(encoding="utf-8")

        # Find lines referencing the message endpoint and verify it's IMMEDIATE
        lines = content.splitlines()
        for line in lines:
            if "/message" in line and ("FIRE_AND_FORGET" in line or "fire_and_forget" in line):
                pytest.fail(
                    "api-server doc still classifies /message as FIRE_AND_FORGET. "
                    "Must be IMMEDIATE per 'already correct' audit classification."
                )


class TestRedisTransportDocResponseMode:
    """Redis transport doc explains how response_mode drives caller behavior."""

    @pytest.mark.unit
    def test_redis_transport_documents_response_mode(self) -> None:
        """The redis transport doc explains response_mode-driven caller behavior."""
        doc = _DOCS_ROOT / "redis-transport.md"
        content = doc.read_text(encoding="utf-8")
        assert "response_mode" in content or "ResponseMode" in content, (
            "redis-transport doc must explain how response_mode determines "
            "whether the caller awaits a response or fires-and-forgets"
        )
