"""Functional test to verify PaneWriter's resilience to subprocess failures."""

from __future__ import annotations

import subprocess
import threading

import pytest

from teleclaude.cli.tui.pane_bridge import PaneWriter

pytestmark = pytest.mark.functional


def test_pane_writer_survives_subprocess_failure():
    """A failing scheduled operation must not terminate the PaneWriter thread."""
    # We can pass None as pane_manager because PaneWriter doesn't invoke methods on it
    writer = PaneWriter(pane_manager=None)

    first_started = threading.Event()
    second_started = threading.Event()

    def failing_op():
        first_started.set()
        raise subprocess.CalledProcessError(1, ["tmux"])

    def success_op():
        second_started.set()

    try:
        # 1. Schedule failing operation
        writer.schedule(failing_op)

        # 2. Wait for it to start, to prevent coalescing
        assert first_started.wait(timeout=2.0), "First operation did not start in time"

        # 3. Schedule successor operation
        writer.schedule(success_op)

        # 4. Assert successor event is set, meaning the writer thread is still alive and processing
        success_ran = second_started.wait(timeout=2.0)
        assert success_ran, "pane-writer thread died on a failing op — subsequent ops never ran"

    finally:
        writer.stop()
