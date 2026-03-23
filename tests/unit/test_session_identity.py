"""Tests for teleclaude.session_identity — file-based session identity resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.session_identity import (
    get_session_id,
    get_session_token,
    get_system_role,
    write_session_identity,
    write_session_identity_to,
)

_IDENTITY_FILENAME = "teleclaude_identity.json"


def _write_identity(tmp_path: Path, data: dict[str, str]) -> None:
    (tmp_path / _IDENTITY_FILENAME).write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# get_session_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reads_session_id(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "abc-123"})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() == "abc-123"


@pytest.mark.unit
def test_returns_none_when_no_tmpdir() -> None:
    with patch.dict("os.environ", {}, clear=True):
        assert get_session_id() is None


@pytest.mark.unit
def test_returns_none_when_file_missing(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() is None


@pytest.mark.unit
def test_returns_none_for_empty_session_id(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": ""})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() is None


@pytest.mark.unit
def test_strips_whitespace(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "  session-456  "})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_id() == "session-456"


@pytest.mark.unit
def test_falls_back_to_tmp(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "from-tmp"})
    with patch.dict("os.environ", {"TMP": str(tmp_path)}, clear=True):
        assert get_session_id() == "from-tmp"


# ---------------------------------------------------------------------------
# get_session_token / get_system_role
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reads_session_token(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "s1", "session_token": "tok-xyz"})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_token() == "tok-xyz"


@pytest.mark.unit
def test_returns_none_when_token_missing(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "s1"})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_session_token() is None


@pytest.mark.unit
def test_reads_system_role(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "s1", "system_role": "integrator"})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        assert get_system_role() == "integrator"


# ---------------------------------------------------------------------------
# write_session_identity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_creates_file(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        write_session_identity("sess-1", session_token="tok-1", system_role="worker")
    data = json.loads((tmp_path / _IDENTITY_FILENAME).read_text())
    assert data["session_id"] == "sess-1"
    assert data["session_token"] == "tok-1"
    assert data["system_role"] == "worker"


@pytest.mark.unit
def test_write_merges_fields(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "sess-1"})
    with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False):
        write_session_identity("sess-1", session_token="tok-2")
    data = json.loads((tmp_path / _IDENTITY_FILENAME).read_text())
    assert data["session_id"] == "sess-1"
    assert data["session_token"] == "tok-2"


@pytest.mark.unit
def test_write_raises_without_tmpdir() -> None:
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="no TMPDIR"):
            write_session_identity("sess-1")


# ---------------------------------------------------------------------------
# write_session_identity_to
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_to_explicit_directory(tmp_path: Path) -> None:
    write_session_identity_to(tmp_path, "sess-2", session_token="tok-3", system_role="orchestrator")
    data = json.loads((tmp_path / _IDENTITY_FILENAME).read_text())
    assert data["session_id"] == "sess-2"
    assert data["session_token"] == "tok-3"
    assert data["system_role"] == "orchestrator"


@pytest.mark.unit
def test_write_to_merges_existing(tmp_path: Path) -> None:
    _write_identity(tmp_path, {"session_id": "sess-2"})
    write_session_identity_to(tmp_path, "sess-2", system_role="integrator")
    data = json.loads((tmp_path / _IDENTITY_FILENAME).read_text())
    assert data["session_id"] == "sess-2"
    assert data["system_role"] == "integrator"
