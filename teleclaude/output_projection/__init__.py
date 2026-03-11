"""Canonical output projection route for TeleClaude.

All output producers and consumers route through this package to apply
shared visibility policy and produce normalized output.

Usage:
    from teleclaude.output_projection import WEB_POLICY, ProjectedBlock
    from teleclaude.output_projection.conversation_projector import project_entries
"""

from teleclaude.output_projection.models import (
    PERMISSIVE_POLICY,
    THREADED_CLEAN_POLICY,
    WEB_POLICY,
    ProjectedBlock,
    TerminalLiveProjection,
    VisibilityPolicy,
)

__all__ = [
    "PERMISSIVE_POLICY",
    "THREADED_CLEAN_POLICY",
    "WEB_POLICY",
    "ProjectedBlock",
    "TerminalLiveProjection",
    "VisibilityPolicy",
]
