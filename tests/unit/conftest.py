"""Unit test conftest — override heavy autouse fixtures with no-ops.

The global tests/conftest.py imports teleclaude.core.db (sqlalchemy + greenlet)
inside autouse fixtures. These cold imports take > 1s in fresh worker processes,
triggering the 1s pytest-timeout. Unit tests in this subtree do not need DB
isolation — they are fully mocked. Override with lightweight stubs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import teleclaude.paths as tc_paths

# Ensure test config path is set (respects CI env var if already set).
_worktree_root = Path(__file__).resolve().parents[2]
os.environ.setdefault("TELECLAUDE_CONFIG_PATH", str(_worktree_root / "tests" / "integration" / "config.yml"))


@pytest.fixture(autouse=True)
def _isolate_test_environment(tmp_path, monkeypatch):
    """Unit tests inherit the suite-level TeleClaude runtime root."""
    assert tc_paths.TELECLAUDE_HOME == Path(os.environ["TELECLAUDE_HOME"])
    yield


@pytest.fixture(autouse=True)
def _isolate_tui_state(tmp_path, monkeypatch):
    """Unit tests inherit TUI state from the suite-level TeleClaude runtime root."""
    assert tc_paths.TUI_STATE_PATH == tc_paths.STATE_DIR / "tui_state.json"
    yield
