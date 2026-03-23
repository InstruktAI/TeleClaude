"""Characterization tests for teleclaude/cli/session_auth.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import teleclaude.cli.session_auth as sa
from teleclaude.cli.session_auth import (
    TerminalAuthState,
    TerminalSessionContext,
    clear_current_session_email,
    get_current_session_context,
    in_tmux_context,
    read_current_session_email,
    write_current_session_email,
)

# ---------------------------------------------------------------------------
# in_tmux_context
# ---------------------------------------------------------------------------


def test_in_tmux_context_returns_true_when_tmux_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
    assert in_tmux_context() is True


def test_in_tmux_context_returns_false_when_tmux_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "")
    assert in_tmux_context() is False


def test_in_tmux_context_returns_false_when_tmux_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    assert in_tmux_context() is False


# ---------------------------------------------------------------------------
# get_current_session_context
# ---------------------------------------------------------------------------


def test_get_current_session_context_returns_context() -> None:
    ctx = get_current_session_context()
    assert ctx is not None
    assert isinstance(ctx.key, str)
    assert isinstance(ctx.tty, str)
    assert isinstance(ctx.auth_path, Path)


def test_get_current_session_context_per_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys007")
    ctx = get_current_session_context()
    assert ctx is not None
    assert ctx.tty == "/dev/ttys007"
    assert ctx.key == "ttys007"
    assert ctx.auth_path.name == "ttys007.json"


def test_get_current_session_context_global_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: None)
    ctx = get_current_session_context()
    assert ctx is not None
    assert ctx.key == "global"
    assert ctx.auth_path.name == "global_identity.json"


# ---------------------------------------------------------------------------
# TerminalSessionContext dataclass
# ---------------------------------------------------------------------------


def test_terminal_session_context_is_frozen() -> None:
    ctx = TerminalSessionContext(tty="", key="global", auth_path=Path("/tmp/identity.json"))
    with pytest.raises(Exception):  # noqa: B017  # FrozenInstanceError (dataclass freeze)
        ctx.key = "other"  # type: ignore[misc,unused-ignore]


# ---------------------------------------------------------------------------
# read_current_session_email
# ---------------------------------------------------------------------------


def test_read_current_session_email_from_per_tty_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    auth_file = tmp_path / "ttys003.json"
    auth_file.write_text(json.dumps({"email": "alice@example.com"}))
    assert read_current_session_email() == "alice@example.com"


def test_read_current_session_email_falls_back_to_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    global_file = tmp_path / "global_identity.json"
    global_file.write_text(json.dumps({"email": "global@example.com"}))
    assert read_current_session_email() == "global@example.com"


def test_read_current_session_email_normalizes_to_lowercase(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    auth_file = tmp_path / "ttys003.json"
    auth_file.write_text(json.dumps({"email": "ALICE@EXAMPLE.COM"}))
    assert read_current_session_email() == "alice@example.com"


def test_read_current_session_email_returns_none_when_no_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    assert read_current_session_email() is None


def test_read_current_session_email_no_tty_reads_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: None)
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    global_file = tmp_path / "global_identity.json"
    global_file.write_text(json.dumps({"email": "bob@example.com"}))
    assert read_current_session_email() == "bob@example.com"


def test_read_current_session_email_from_plain_text_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    auth_file = tmp_path / "ttys003.json"
    auth_file.write_text("carol@example.com\n")
    assert read_current_session_email() == "carol@example.com"


# ---------------------------------------------------------------------------
# write_current_session_email
# ---------------------------------------------------------------------------


def test_write_current_session_email_creates_per_tty_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    result = write_current_session_email("dave@example.com")
    assert (tmp_path / "ttys003.json").exists()
    assert result.email == "dave@example.com"
    assert isinstance(result, TerminalAuthState)


def test_write_current_session_email_normalizes_email(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    result = write_current_session_email("EVE@EXAMPLE.COM")
    assert result.email == "eve@example.com"


def test_write_current_session_email_rejects_invalid_email(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    with pytest.raises(ValueError):
        write_current_session_email("not-an-email")


def test_write_current_session_email_stores_json_with_tty_and_timestamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    write_current_session_email("frank@example.com")
    data = json.loads((tmp_path / "ttys003.json").read_text())
    assert data["email"] == "frank@example.com"
    assert data["tty"] == "/dev/ttys003"
    assert "updated_at" in data


def test_write_current_session_email_no_tty_writes_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: None)
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    result = write_current_session_email("global@example.com")
    assert (tmp_path / "global_identity.json").exists()
    assert result.email == "global@example.com"


# ---------------------------------------------------------------------------
# clear_current_session_email
# ---------------------------------------------------------------------------


def test_clear_current_session_email_deletes_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    auth_file = tmp_path / "ttys003.json"
    auth_file.write_text(json.dumps({"email": "grace@example.com"}))
    assert clear_current_session_email() is True
    assert not auth_file.exists()


def test_clear_current_session_email_returns_false_when_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sa, "_detect_tty", lambda: "/dev/ttys003")
    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", tmp_path)
    assert clear_current_session_email() is False
