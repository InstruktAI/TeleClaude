# guard: no-companion
"""Spec tests (xfail) for cadence-file-authority - R9: Removal of superseded mechanisms.

Structural tests verifying that code paths made redundant by file-derived rendering
authority (R1-R8) have been removed. Uses AST inspection modeled on
test_todo_watcher_removal.py.

R9 items:
- last_tool_done_at as a rendering cursor in the cadence loop
- last_delivered_at seal and delivery_ts guard in send_threaded_output
- has_active_output_message conditional cursor advancement in the cadence loop
- _reflect_user_input as a separate mechanism in the cadence loop
- Coordinator-owned rendering state manipulation in break_threaded_turn and
  handle_user_prompt_submit
- force_session_output_pull call for terminal input in handle_user_prompt_submit
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# R9.1 — last_tool_done_at removed as rendering cursor from cadence
# ---------------------------------------------------------------------------


class TestLastToolDoneAtRemovedFromCadence:
    """The cadence loop must not use last_tool_done_at as a rendering cursor."""

    def test_cadence_does_not_read_last_tool_done_at(self) -> None:
        """OutputCadenceLoop must not access session.last_tool_done_at."""
        cadence_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")

        assert "last_tool_done_at" not in source, (
            "output_cadence.py still references last_tool_done_at — "
            "the cadence must derive rendering windows from the transcript file (R1/R9)"
        )

    def test_cadence_does_not_import_has_active_output_message(self) -> None:
        """has_active_output_message is only needed for conditional cursor advancement.
        With file-derived authority, this import is unnecessary."""
        cadence_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.names:
                    imported_names = [alias.name for alias in node.names]
                    assert "has_active_output_message" not in imported_names, (
                        "output_cadence.py still imports has_active_output_message — "
                        "conditional cursor advancement is superseded (R9)"
                    )

    def test_cadence_does_not_update_session_last_tool_done_at(self) -> None:
        """The cadence must not write last_tool_done_at via db.update_session."""
        cadence_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")

        # Check for the specific SessionField.LAST_TOOL_DONE_AT usage
        assert "LAST_TOOL_DONE_AT" not in source, (
            "output_cadence.py still uses SessionField.LAST_TOOL_DONE_AT — "
            "the cadence must not update external cursors (R9)"
        )


# ---------------------------------------------------------------------------
# R9.2 — last_delivered_at seal and delivery_ts guard removed from send_threaded_output
# ---------------------------------------------------------------------------


class TestDeliveryTsGuardRemoved:
    """The delivery_ts guard in send_threaded_output is superseded by
    correct-by-construction rendering from file authority."""

    def test_send_threaded_output_no_delivery_ts_parameter(self) -> None:
        """send_threaded_output must not accept a delivery_ts parameter.
        File-derived rendering eliminates the TOCTOU race this guarded against."""
        ui_adapter_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui_adapter.py"
        source = ui_adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_threaded_output":
                param_names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
                assert "delivery_ts" not in param_names, (
                    "send_threaded_output still accepts delivery_ts — "
                    "the TOCTOU guard is superseded by file-derived rendering (R9)"
                )
                break
        else:
            pytest.fail("send_threaded_output not found in ui_adapter.py")

    def test_send_threaded_output_no_sealed_delivery_check(self) -> None:
        """send_threaded_output must not read last_delivered_at to reject deliveries.
        Both the delivery seal ('sealed') AND the last_delivered_at guard must be absent —
        correct-by-construction rendering eliminates both."""
        ui_adapter_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui_adapter.py"
        source = ui_adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_threaded_output":
                method_source = ast.get_source_segment(source, node) or ""
                assert "last_delivered_at" not in method_source, (
                    "send_threaded_output still references last_delivered_at — "
                    "the delivery window seal is superseded by file-derived rendering (R9)"
                )
                assert "sealed" not in method_source.lower(), (
                    "send_threaded_output still checks 'sealed' condition — "
                    "the TOCTOU guard is superseded by correct-by-construction rendering (R9)"
                )
                break
        else:
            pytest.fail("send_threaded_output not found in ui_adapter.py")


# ---------------------------------------------------------------------------
# R9.3 — has_active_output_message conditional cursor advancement removed
# ---------------------------------------------------------------------------


class TestConditionalCursorAdvancementRemoved:
    """The has_active_output_message check that conditionally skips cursor
    advancement in the cadence loop is superseded."""

    def test_cadence_no_has_active_output_message_call(self) -> None:
        """The cadence loop must not call has_active_output_message."""
        cadence_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")

        assert "has_active_output_message" not in source, (
            "output_cadence.py still calls has_active_output_message — "
            "conditional cursor advancement is superseded by file-derived rendering (R9)"
        )


# ---------------------------------------------------------------------------
# R9.4 — _reflect_user_input removed from cadence loop
# ---------------------------------------------------------------------------


class TestReflectUserInputRemoved:
    """_reflect_user_input is superseded by the unified content belt (R5)."""

    def test_cadence_no_reflect_user_input_method(self) -> None:
        """OutputCadenceLoop must not define _reflect_user_input."""
        cadence_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "OutputCadenceLoop":
                method_names = [
                    item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                assert "_reflect_user_input" not in method_names, (
                    "OutputCadenceLoop still defines _reflect_user_input — "
                    "unified content belt replaces separate reflection (R5/R9)"
                )
                break
        else:
            pytest.fail("OutputCadenceLoop class not found in output_cadence.py")


# ---------------------------------------------------------------------------
# R9.5 — Coordinator rendering state manipulation removed
# ---------------------------------------------------------------------------


class TestCoordinatorRenderingStateRemoved:
    """Coordinator must not manipulate rendering state (last_tool_done_at for
    rendering purposes, clear_turn_state calls)."""

    def test_break_threaded_turn_no_clear_turn_state(self) -> None:
        """break_threaded_turn must not broadcast clear_turn_state."""
        output_mixin_path = _REPO_ROOT / "teleclaude" / "core" / "adapter_client" / "_output.py"
        source = output_mixin_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "break_threaded_turn":
                method_source = ast.get_source_segment(source, node) or ""
                assert "clear_turn_state" not in method_source, (
                    "break_threaded_turn still references clear_turn_state — "
                    "rendering state manipulation must be removed (R6/R9)"
                )
                break
        else:
            pytest.fail("break_threaded_turn not found in _output.py")

    def test_break_threaded_turn_no_cursor_advancement(self) -> None:
        """break_threaded_turn must not advance the cadence cursor."""
        output_mixin_path = _REPO_ROOT / "teleclaude" / "core" / "adapter_client" / "_output.py"
        source = output_mixin_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "break_threaded_turn":
                method_source = ast.get_source_segment(source, node) or ""
                assert "last_tool_done_at" not in method_source, (
                    "break_threaded_turn still writes last_tool_done_at — "
                    "cursor advancement is not a lifecycle concern (R9)"
                )
                break
        else:
            pytest.fail("break_threaded_turn not found in _output.py")

    def test_handle_user_prompt_submit_no_rendering_cursor(self) -> None:
        """handle_user_prompt_submit must not set last_tool_done_at."""
        coordinator_path = _REPO_ROOT / "teleclaude" / "core" / "agent_coordinator" / "_coordinator.py"
        source = coordinator_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_user_prompt_submit":
                method_source = ast.get_source_segment(source, node) or ""
                assert "last_tool_done_at" not in method_source, (
                    "handle_user_prompt_submit still manipulates last_tool_done_at — "
                    "rendering cursors belong to the cadence (R7/R9)"
                )
                break
        else:
            pytest.fail("handle_user_prompt_submit not found in _coordinator.py")


# ---------------------------------------------------------------------------
# R9.6 — force_session_output_pull for terminal input removed
# ---------------------------------------------------------------------------


class TestForceOutputPullTerminalRemoved:
    """force_session_output_pull call for terminal input in handle_user_prompt_submit
    is superseded by rendering parity (R8)."""

    def test_handle_user_prompt_submit_no_force_pull(self) -> None:
        """handle_user_prompt_submit must not call force_session_output_pull."""
        coordinator_path = _REPO_ROOT / "teleclaude" / "core" / "agent_coordinator" / "_coordinator.py"
        source = coordinator_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_user_prompt_submit":
                method_source = ast.get_source_segment(source, node) or ""
                assert "force_session_output_pull" not in method_source, (
                    "handle_user_prompt_submit still calls force_session_output_pull — "
                    "terminal input must use the cadence rendering path (R8/R9)"
                )
                break
        else:
            pytest.fail("handle_user_prompt_submit not found in _coordinator.py")

    def test_clear_turn_state_not_called_from_adapter_runtime(self) -> None:
        """clear_turn_state must not be called from the adapter runtime layer (_output.py).
        The cadence owns delivery bookkeeping resets."""
        output_mixin_path = _REPO_ROOT / "teleclaude" / "core" / "adapter_client" / "_output.py"
        source = output_mixin_path.read_text(encoding="utf-8")

        assert "clear_turn_state" not in source, (
            "_output.py still references clear_turn_state — "
            "the lifecycle layer must not manipulate rendering state (R3/R9)"
        )
