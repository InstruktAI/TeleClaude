"""Characterization tests for teleclaude.output_projection.terminal_live_projector."""

from __future__ import annotations

import pytest

from teleclaude.output_projection.terminal_live_projector import project_terminal_live


class TestProjectTerminalLive:
    @pytest.mark.unit
    def test_wraps_output_in_terminal_live_projection(self) -> None:
        projection = project_terminal_live("clean snapshot")

        assert projection.output == "clean snapshot"
