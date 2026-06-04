"""Snapshot tests for static constants with runtime contract impact."""

from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import AGENT_PROTOCOL

pytestmark = pytest.mark.unit


def test_gemini_launch_profiles(snapshot: SnapshotAssertion) -> None:
    profiles = AGENT_PROTOCOL["gemini"]["profiles"]

    assert profiles == snapshot
