"""Tests for teleclaude.session_identity — file-based session ID resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.session_identity import get_session_id


@pytest.mark.unit
def test_reads_marker_file(tmp_path: Path) -> None:
    """Returns session ID from the marker file in TMPDIR."""
    marker = tmp_path / "teleclaude_session_id"
    marker.write_text("abc-123\n")
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() == "abc-123"


@pytest.mark.unit
def test_returns_none_when_no_tmpdir() -> None:
    """Returns None when TMPDIR/TMP/TEMP are all unset."""
    with patch.dict("os.environ", {}, clear=True):
        assert get_session_id() is None


@pytest.mark.unit
def test_returns_none_when_marker_missing(tmp_path: Path) -> None:
    """Returns None when marker file does not exist."""
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() is None


@pytest.mark.unit
def test_returns_none_for_empty_marker(tmp_path: Path) -> None:
    """Returns None when marker file is empty."""
    marker = tmp_path / "teleclaude_session_id"
    marker.write_text("")
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() is None


@pytest.mark.unit
def test_strips_whitespace(tmp_path: Path) -> None:
    """Strips leading/trailing whitespace from marker content."""
    marker = tmp_path / "teleclaude_session_id"
    marker.write_text("  session-456  \n")
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() == "session-456"


@pytest.mark.unit
def test_falls_back_to_tmp(tmp_path: Path) -> None:
    """Falls back to TMP when TMPDIR is not set."""
    marker = tmp_path / "teleclaude_session_id"
    marker.write_text("from-tmp")
    with patch.dict("os.environ", {"TMP": str(tmp_path)}, clear=True):
        assert get_session_id() == "from-tmp"
