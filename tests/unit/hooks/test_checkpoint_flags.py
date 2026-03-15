"""Characterization tests for teleclaude.hooks.checkpoint_flags."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_CLEAR_FLAG,
    _safe_session_path_component,
    checkpoint_flag_path,
    consume_checkpoint_flag,
    has_checkpoint_flag,
    is_checkpoint_disabled,
    session_tmp_base_dir,
    set_checkpoint_flag,
)


class TestSessionTmpBaseDir:
    @pytest.mark.unit
    def test_uses_environment_override_when_present(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path / "sessions"))

        assert session_tmp_base_dir() == (tmp_path / "sessions").resolve()


class TestSafeSessionPathComponent:
    @pytest.mark.unit
    def test_hashes_session_ids_that_are_not_filesystem_safe(self) -> None:
        raw_session_id = "session:with/slash"

        assert (
            _safe_session_path_component(raw_session_id)
            == hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()[:32]
        )


class TestCheckpointFlags:
    @pytest.mark.unit
    def test_set_and_consume_round_trip_creates_and_removes_the_flag_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

        flag_path = checkpoint_flag_path("session:with/slash", "custom-flag")

        assert has_checkpoint_flag("session:with/slash", "custom-flag") is False

        set_checkpoint_flag("session:with/slash", "custom-flag")

        assert flag_path.exists() is True
        assert has_checkpoint_flag("session:with/slash", "custom-flag") is True
        assert consume_checkpoint_flag("session:with/slash", "custom-flag") is True
        assert flag_path.exists() is False

    @pytest.mark.unit
    def test_is_checkpoint_disabled_tracks_the_clear_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

        assert is_checkpoint_disabled("session-1") is False

        set_checkpoint_flag("session-1", CHECKPOINT_CLEAR_FLAG)

        assert is_checkpoint_disabled("session-1") is True
