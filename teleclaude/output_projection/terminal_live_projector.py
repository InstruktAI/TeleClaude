"""Canonical terminal live output projection route.

Wraps poller-driven tmux snapshot output through the shared projection layer.
"""

from __future__ import annotations

from teleclaude.output_projection.models import TerminalLiveProjection


def project_terminal_live(output: str) -> TerminalLiveProjection:
    """Wrap clean poller output in a TerminalLiveProjection.

    Routes poller output through the shared projection layer while preserving
    the existing adapter-facing send_output_update() contract. The caller
    passes projection.output to the adapter unchanged.

    Args:
        output: ANSI-stripped clean terminal snapshot from the poller.

    Returns:
        TerminalLiveProjection wrapping the output.
    """
    return TerminalLiveProjection(output=output)
