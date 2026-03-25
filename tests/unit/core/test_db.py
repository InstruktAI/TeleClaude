# guard: no-companion
"""Tests for teleclaude.core.db — principal resolution edge cases.

Core principal resolution is tested in test__sync.py with real Session objects.
This file covers edge cases that benefit from explicit construction.
"""

from __future__ import annotations

import pytest

from teleclaude.core.db import resolve_session_principal
from teleclaude.core.models import Session


@pytest.mark.unit
def test_system_principal_does_not_truncate_session_id():
    """Identity invariant: system principals must use the full UUID, never truncated."""
    long_id = "a" * 64
    session = Session(
        session_id=long_id,
        computer_name="x",
        tmux_session_name="t",
        title="S",
        system_role="worker",
    )
    principal, _ = resolve_session_principal(session)
    assert long_id in principal
