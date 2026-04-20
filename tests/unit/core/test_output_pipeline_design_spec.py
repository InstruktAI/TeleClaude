# guard: no-companion

"""Structural specs for the central transcript-driven output pipeline.

These tests document the intended ownership model:

- tmux is a lightweight change detector only
- transcript/files are the canonical output source
- the core coordinator builds output centrally
- adapters receive pushed output and perform delivery only
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core import output_poller
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.polling_coordinator import _build_transcript_output_update

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestTmuxHotPathBounded:
    def test_output_poller_hot_path_capture_window_is_small(self) -> None:
        assert output_poller._HOT_PATH_CAPTURE_LINES == 20

    def test_output_poller_passes_hot_path_capture_window_to_tmux_bridge(self) -> None:
        source = inspect.getsource(OutputPoller.poll)

        assert "capture_lines=_HOT_PATH_CAPTURE_LINES" in source, (
            "OutputPoller.poll must keep tmux scanning bounded on the hot path"
        )


class TestCoordinatorOwnsCanonicalRendering:
    def test_coordinator_builds_output_from_transcript_helpers(self) -> None:
        source = inspect.getsource(_build_transcript_output_update)

        assert "get_assistant_messages_since" in source
        assert "render_agent_output" in source
        assert "render_clean_agent_output" in source

    def test_polling_coordinator_pushes_output_updates_to_adapters(self) -> None:
        coordinator_path = _REPO_ROOT / "teleclaude" / "core" / "polling_coordinator.py"
        source = coordinator_path.read_text(encoding="utf-8")

        assert "adapter_client.send_output_update(" in source, (
            "The coordinator must push transcript-derived output to adapters centrally"
        )


class TestAdaptersStayTransportFocused:
    def test_ui_adapter_has_no_output_cadence_loop_import(self) -> None:
        ui_adapter_path = _REPO_ROOT / "teleclaude" / "adapters" / "ui_adapter.py"
        source = ui_adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "teleclaude.adapters.ui.output_cadence", (
                    "UiAdapter must not own a separate output cadence loop"
                )

    def test_ui_adapter_send_output_update_delegates_to_threaded_delivery(self) -> None:
        source = inspect.getsource(UiAdapter.send_output_update)

        assert "send_threaded_output" in source, "UiAdapter.send_output_update should remain a thin delivery adapter"
