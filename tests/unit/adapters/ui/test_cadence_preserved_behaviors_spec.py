# guard: no-companion
"""Spec tests (non-xfail) for cadence-file-authority - R10: Preserved behaviors.

These tests assert that existing behaviors are NOT broken by the file-authority
refactoring. They pass today and must continue to pass after R1-R9 are implemented.
They serve as regression guards for the builder.

R10 preserved behaviors:
- char_offset and output_message_id delivery bookkeeping mechanisms (UiAdapter)
- last_input_origin for rendering mode determination (Session model)
- Transcript parser function signatures (file path + agent name + optional cursor)
- force_session_output_pull preserved for final-flush (already guarded in R8 section)
- Cadence activation path via last_activity_at → get_sessions_active_since
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client._output import _OutputMixin
from teleclaude.core.models import Session
from teleclaude.utils.transcript import get_assistant_messages_since, render_clean_agent_output

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# R10.1 — char_offset and output_message_id mechanisms preserved on UiAdapter
# ---------------------------------------------------------------------------


class TestDeliveryBookkeepingMechanismPreserved:
    """UiAdapter must retain its char_offset and output_message_id helpers.

    R3 transfers ownership of these fields to the cadence, but the UiAdapter
    still provides the low-level read/write primitives. Removing them would
    break the send_threaded_output pipeline regardless of who calls it.
    """

    def test_ui_adapter_has_char_offset_read_method(self) -> None:
        """UiAdapter must have _get_char_offset for reading delivery position."""
        assert hasattr(UiAdapter, "_get_char_offset"), (
            "UiAdapter._get_char_offset was removed — char_offset bookkeeping mechanism must be preserved (R10)"
        )

    def test_ui_adapter_has_char_offset_write_method(self) -> None:
        """UiAdapter must have _set_char_offset for writing delivery position."""
        assert hasattr(UiAdapter, "_set_char_offset"), (
            "UiAdapter._set_char_offset was removed — char_offset bookkeeping mechanism must be preserved (R10)"
        )

    def test_ui_adapter_has_output_message_id_read_method(self) -> None:
        """UiAdapter must have _get_output_message_id for reading platform ref."""
        assert hasattr(UiAdapter, "_get_output_message_id"), (
            "UiAdapter._get_output_message_id was removed — "
            "output_message_id bookkeeping mechanism must be preserved (R10)"
        )

    def test_ui_adapter_has_output_message_id_store_method(self) -> None:
        """UiAdapter must have _store_output_message_id for writing platform ref."""
        assert hasattr(UiAdapter, "_store_output_message_id"), (
            "UiAdapter._store_output_message_id was removed — "
            "output_message_id bookkeeping mechanism must be preserved (R10)"
        )

    def test_ui_adapter_has_output_message_id_clear_method(self) -> None:
        """UiAdapter must have _clear_output_message_id for resetting platform ref."""
        assert hasattr(UiAdapter, "_clear_output_message_id"), (
            "UiAdapter._clear_output_message_id was removed — "
            "output_message_id bookkeeping mechanism must be preserved (R10)"
        )

    def test_send_threaded_output_exists_on_ui_adapter(self) -> None:
        """send_threaded_output must still exist as the delivery entry point."""
        assert hasattr(UiAdapter, "send_threaded_output"), (
            "UiAdapter.send_threaded_output was removed — threaded output delivery must be preserved (R10)"
        )


# ---------------------------------------------------------------------------
# R10.2 — last_input_origin preserved on Session model
# ---------------------------------------------------------------------------


class TestLastInputOriginPreserved:
    """Session.last_input_origin must remain a first-class field.

    R4 reads it at render time to determine origin vs. reflection mode.
    Removing it would break the transient rendering mode mechanism.
    """

    def test_session_has_last_input_origin_field(self) -> None:
        """Session must expose last_input_origin as an accessible attribute."""
        session = Session(
            session_id="sess-r10",
            computer_name="local",
            tmux_session_name="test",
            title="R10 Test",
            last_input_origin="telegram",
        )
        assert session.last_input_origin == "telegram", (
            "Session.last_input_origin field was removed or does not round-trip — "
            "rendering mode determination requires this field (R10)"
        )

    def test_session_last_input_origin_defaults_to_none(self) -> None:
        """Session.last_input_origin must be None when not set."""
        session = Session(
            session_id="sess-r10b",
            computer_name="local",
            tmux_session_name="test",
            title="R10 Test",
        )
        assert session.last_input_origin is None, (
            "Session.last_input_origin must default to None — rendering mode falls back to origin mode when unset (R10)"
        )


# ---------------------------------------------------------------------------
# R10.3 — Transcript parser function signatures preserved
# ---------------------------------------------------------------------------


class TestTranscriptParserInterfacesPreserved:
    """Transcript parser functions must preserve their file-path-based signatures.

    These are the functions the cadence calls to read the transcript file.
    R1 requires file-derived authority — if the signatures change to drop
    the file path argument, the whole file-authority model breaks.
    """

    def test_get_assistant_messages_since_accepts_path_and_agent(self) -> None:
        """get_assistant_messages_since must accept (transcript_path, agent_name, ...)."""
        sig = inspect.signature(get_assistant_messages_since)
        params = list(sig.parameters.keys())
        assert "transcript_path" in params, (
            "get_assistant_messages_since lost transcript_path parameter — "
            "file-derived rendering depends on this interface (R10)"
        )
        assert "agent_name" in params, (
            "get_assistant_messages_since lost agent_name parameter — "
            "file-derived rendering depends on this interface (R10)"
        )

    def test_get_assistant_messages_since_has_optional_since_timestamp(self) -> None:
        """get_assistant_messages_since must accept an optional since_timestamp."""
        sig = inspect.signature(get_assistant_messages_since)
        assert "since_timestamp" in sig.parameters, (
            "get_assistant_messages_since lost since_timestamp parameter — "
            "the cadence uses this to read from the file cursor (R10)"
        )
        param = sig.parameters["since_timestamp"]
        assert param.default is not inspect.Parameter.empty, (
            "since_timestamp must be optional — cadence calls it without a cursor on new turns (R10)"
        )

    def test_render_clean_agent_output_accepts_path_and_agent(self) -> None:
        """render_clean_agent_output must accept (transcript_path, agent_name, ...)."""
        sig = inspect.signature(render_clean_agent_output)
        params = list(sig.parameters.keys())
        assert "transcript_path" in params, (
            "render_clean_agent_output lost transcript_path parameter — "
            "file-derived rendering depends on this interface (R10)"
        )
        assert "agent_name" in params, (
            "render_clean_agent_output lost agent_name parameter — "
            "file-derived rendering depends on this interface (R10)"
        )

    def test_render_clean_agent_output_returns_content_and_timestamp(self) -> None:
        """render_clean_agent_output must return (str | None, datetime | None)."""
        hints = render_clean_agent_output.__annotations__
        return_annotation = hints.get("return", "")
        annotation_str = str(return_annotation).lower()
        assert "tuple" in annotation_str, (
            "render_clean_agent_output return type changed — cadence depends on (text, timestamp) tuple contract (R10)"
        )


# ---------------------------------------------------------------------------
# R10.4 — Cadence activation path via last_activity_at preserved
# ---------------------------------------------------------------------------


class TestCadenceActivationPathPreserved:
    """The cadence loop must activate via get_sessions_active_since,
    which is driven by last_activity_at written by TMUX and agent event signals.

    This is the preserved signal → last_activity_at → cadence activation pattern.
    """

    def test_cadence_tick_queries_sessions_active_since(self) -> None:
        """OutputCadenceLoop._tick must call db.get_sessions_active_since.

        This is the join point between the signal path and the cadence.
        TMUX activity and agent events update last_activity_at; the cadence
        reads it via get_sessions_active_since. Removing this call would
        sever the activation path.
        """
        cadence_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        tick_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_tick":
                tick_found = True
                method_source = ast.get_source_segment(source, node) or ""
                assert "get_sessions_active_since" in method_source, (
                    "_tick no longer calls db.get_sessions_active_since — "
                    "the TMUX signal → last_activity_at → cadence activation path is broken (R10)"
                )
                break

        assert tick_found, "_tick method not found in OutputCadenceLoop"

    def test_output_mixin_has_force_session_output_pull(self) -> None:
        """force_session_output_pull must exist on _OutputMixin for final flush.

        This duplicates the R8 preservation test to make the R10 coverage
        self-contained, since R8 and R10 both guarantee this method exists.
        """
        assert hasattr(_OutputMixin, "force_session_output_pull"), (
            "force_session_output_pull was removed from _OutputMixin — "
            "it must be preserved for final-flush before session close (R10)"
        )


# ---------------------------------------------------------------------------
# R7 — Agent event signal handlers already correctly separated (regression guard)
# ---------------------------------------------------------------------------


class TestAgentEventSignalHandlersSeparation:
    """Agent event handlers (handle_tool_done, handle_agent_stop) are already
    correctly separated from rendering state. These regression guards ensure the
    refactoring does not accidentally introduce rendering state into them.

    Completes R7 signal handler coverage (TMUX was already added as xfail;
    these handlers are already correct so they are non-xfail preservation guards).
    """

    def test_handle_tool_done_does_not_touch_rendering_state(self) -> None:
        """handle_tool_done must not reference rendering state tokens.
        It drives headless output delivery via last_activity_at only."""
        _repo_root = Path(__file__).resolve().parents[4]
        coordinator_path = _repo_root / "teleclaude" / "core" / "agent_coordinator" / "_coordinator.py"
        source = coordinator_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        rendering_state_tokens = {
            "last_tool_done_at",
            "LAST_TOOL_DONE_AT",
            "char_offset",
            "output_message_id",
            "last_delivered_at",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_tool_done":
                method_source = ast.get_source_segment(source, node) or ""
                for token in rendering_state_tokens:
                    assert token not in method_source, (
                        f"handle_tool_done references '{token}' — "
                        "agent event signal handler must not touch rendering state (R7)"
                    )
                return
        pytest.fail("handle_tool_done not found in AgentCoordinator")

    def test_handle_agent_stop_does_not_touch_rendering_state(self) -> None:
        """handle_agent_stop must not reference rendering state tokens.
        It updates last_activity_at and last_agent_stop_at only."""
        _repo_root = Path(__file__).resolve().parents[4]
        coordinator_path = _repo_root / "teleclaude" / "core" / "agent_coordinator" / "_coordinator.py"
        source = coordinator_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        rendering_state_tokens = {
            "last_tool_done_at",
            "LAST_TOOL_DONE_AT",
            "char_offset",
            "output_message_id",
            "last_delivered_at",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_agent_stop":
                method_source = ast.get_source_segment(source, node) or ""
                for token in rendering_state_tokens:
                    assert token not in method_source, (
                        f"handle_agent_stop references '{token}' — "
                        "agent event signal handler must not touch rendering state (R7)"
                    )
                return
        pytest.fail("handle_agent_stop not found in AgentCoordinator")
