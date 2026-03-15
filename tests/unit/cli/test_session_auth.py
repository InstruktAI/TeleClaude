"""Characterization tests for teleclaude/cli/session_auth.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_get_current_session_context_returns_global_context() -> None:
    ctx = get_current_session_context()
    assert ctx is not None
    assert ctx.key == "global"
    assert ctx.tty == ""
    assert isinstance(ctx.auth_path, Path)


# ---------------------------------------------------------------------------
# TerminalSessionContext dataclass
# ---------------------------------------------------------------------------


def test_terminal_session_context_is_frozen() -> None:
    ctx = TerminalSessionContext(tty="", key="global", auth_path=Path("/tmp/identity.json"))
    with pytest.raises(Exception):  # noqa: B017  # FrozenInstanceError (dataclass freeze)
        ctx.key = "other"


# ---------------------------------------------------------------------------
# read_current_session_email — env var path
# ---------------------------------------------------------------------------


def test_read_current_session_email_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEC_AUTH_EMAIL", "alice@example.com")
    result = read_current_session_email()
    assert result == "alice@example.com"


def test_read_current_session_email_normalizes_to_lowercase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEC_AUTH_EMAIL", "ALICE@EXAMPLE.COM")
    result = read_current_session_email()
    assert result == "alice@example.com"


def test_read_current_session_email_returns_none_for_empty_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEC_AUTH_EMAIL", "  ")
    # Prevent reading real auth file by patching AUTH_PATH to nonexistent file
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "AUTH_PATH", tmp_path / "identity.json")
    result = read_current_session_email()
    assert result is None


# ---------------------------------------------------------------------------
# read_current_session_email — file path
# ---------------------------------------------------------------------------


def test_read_current_session_email_from_json_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEC_AUTH_EMAIL", raising=False)
    auth_file = tmp_path / "identity.json"
    auth_file.write_text(json.dumps({"email": "bob@example.com"}))
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    result = read_current_session_email()
    assert result == "bob@example.com"


def test_read_current_session_email_from_plain_text_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEC_AUTH_EMAIL", raising=False)
    auth_file = tmp_path / "identity.json"
    auth_file.write_text("carol@example.com\n")
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    result = read_current_session_email()
    assert result == "carol@example.com"


def test_read_current_session_email_returns_none_when_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TELEC_AUTH_EMAIL", raising=False)
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "AUTH_PATH", tmp_path / "identity.json")
    result = read_current_session_email()
    assert result is None


# ---------------------------------------------------------------------------
# write_current_session_email
# ---------------------------------------------------------------------------


def test_write_current_session_email_creates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_dir = tmp_path / "session-auth"
    auth_file = auth_dir / "identity.json"
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", auth_dir)
    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    result = write_current_session_email("dave@example.com")
    assert auth_file.exists()
    assert result.email == "dave@example.com"
    assert isinstance(result, TerminalAuthState)


def test_write_current_session_email_normalizes_email(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_dir = tmp_path / "session-auth"
    auth_file = auth_dir / "identity.json"
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", auth_dir)
    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    result = write_current_session_email("EVE@EXAMPLE.COM")
    assert result.email == "eve@example.com"


def test_write_current_session_email_rejects_invalid_email(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_dir = tmp_path / "session-auth"
    auth_file = auth_dir / "identity.json"
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", auth_dir)
    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    with pytest.raises(ValueError):
        write_current_session_email("not-an-email")


def test_write_current_session_email_stores_json_with_updated_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth_dir = tmp_path / "session-auth"
    auth_file = auth_dir / "identity.json"
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "SESSION_AUTH_DIR", auth_dir)
    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    write_current_session_email("frank@example.com")
    data = json.loads(auth_file.read_text())
    assert data["email"] == "frank@example.com"
    assert "updated_at" in data


# ---------------------------------------------------------------------------
# clear_current_session_email
# ---------------------------------------------------------------------------


def test_clear_current_session_email_deletes_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    auth_file = tmp_path / "identity.json"
    auth_file.write_text(json.dumps({"email": "grace@example.com"}))
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "AUTH_PATH", auth_file)
    result = clear_current_session_email()
    assert result is True
    assert not auth_file.exists()


def test_clear_current_session_email_returns_false_when_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import teleclaude.cli.session_auth as sa

    monkeypatch.setattr(sa, "AUTH_PATH", tmp_path / "identity.json")
    result = clear_current_session_email()
    assert result is False
