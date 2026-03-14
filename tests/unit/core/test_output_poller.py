"""Characterization tests for teleclaude.core.output_poller."""

from __future__ import annotations

import pytest

from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputEvent,
    OutputPoller,
    ProcessExited,
)


class TestOutputEventDataclasses:
    # OutputEvent subclasses are plain dataclasses with no computed properties
    # or validation. Field storage is the public contract; these tests pin it.
    @pytest.mark.unit
    def test_output_changed_fields(self):
        event = OutputChanged(
            session_id="sess-001",
            output="some output",
            started_at=1000.0,
            last_changed_at=1005.0,
        )
        assert event.session_id == "sess-001"
        assert event.output == "some output"

    @pytest.mark.unit
    def test_process_exited_fields(self):
        event = ProcessExited(
            session_id="sess-001",
            exit_code=0,
            final_output="done",
            started_at=1000.0,
        )
        assert event.session_id == "sess-001"
        assert event.exit_code == 0
        assert event.final_output == "done"

    @pytest.mark.unit
    def test_directory_changed_fields(self):
        event = DirectoryChanged(
            session_id="sess-001",
            new_path="/new",
            old_path="/old",
        )
        assert event.new_path == "/new"
        assert event.old_path == "/old"

    @pytest.mark.unit
    def test_output_event_is_base_for_output_changed(self):
        event = OutputChanged(
            session_id="sess-001",
            output="",
            started_at=0.0,
            last_changed_at=0.0,
        )
        assert isinstance(event, OutputEvent)

    @pytest.mark.unit
    def test_process_exited_none_exit_code_allowed(self):
        event = ProcessExited(
            session_id="sess-001",
            exit_code=None,
            final_output="",
            started_at=0.0,
        )
        assert event.exit_code is None


class TestOutputPoller:
    @pytest.mark.unit
    def test_instantiates(self):
        poller = OutputPoller()
        assert isinstance(poller, OutputPoller)
