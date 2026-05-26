"""Characterization tests for teleclaude.services.email."""

from __future__ import annotations

from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.services.email import send_email


class _RecordingSMTP:
    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.login_args: tuple[str, str] | None = None
        self.sendmail_args: tuple[str, str, str] | None = None
        self.started_tls = False

    def __enter__(self) -> _RecordingSMTP:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        return False

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def sendmail(self, sender: str, recipient: str, message: str) -> None:
        self.sendmail_args = (sender, recipient, message)


async def _run_sync(func: object) -> None:
    assert callable(func)
    func()


_SMTP_USER = "smtp-user"
_SMTP_KEY = "smtp-key"
_SENDER_ADDR = "sender@example.com"
_EMAIL_FROM = f"Sender Name <{_SENDER_ADDR}>"
_REPLY_TO = "No Reply <no-reply@example.com>"
_RECIPIENT = "person@example.com"


def _set_smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_USERNAME", _SMTP_USER)
    monkeypatch.setenv("SMTP_KEY", _SMTP_KEY)
    monkeypatch.setenv("EMAIL_FROM", _EMAIL_FROM)
    monkeypatch.setenv("SMTP_RELAY", "smtp.test:2525")
    monkeypatch.setenv("EMAIL_REPLYTO", _REPLY_TO)


class TestSendEmail:
    @pytest.mark.unit
    async def test_requires_smtp_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SMTP_KEY", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)

        with pytest.raises(ValueError, match="Missing required SMTP credentials"):
            await send_email(_RECIPIENT, "Subject", "<p>Hello</p>")

    @pytest.mark.unit
    async def test_sends_with_envelope_sender_replyto_and_text_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_smtp_env(monkeypatch)
        smtp = _RecordingSMTP("smtp.test", 2525, timeout=10)

        with (
            patch("teleclaude.services.email.asyncio.to_thread", new=AsyncMock(side_effect=_run_sync)),
            patch("teleclaude.services.email.smtplib.SMTP", return_value=smtp),
        ):
            await send_email(_RECIPIENT, "Subject", "<h1>Hello</h1><p>World</p>")

        assert smtp.started_tls is True
        assert smtp.login_args == (_SMTP_USER, _SMTP_KEY)
        assert smtp.sendmail_args is not None
        # Envelope sender is the bare address parsed out of EMAIL_FROM.
        assert smtp.sendmail_args[0] == _SENDER_ADDR
        assert smtp.sendmail_args[1] == _RECIPIENT
        message = smtp.sendmail_args[2]
        assert "HelloWorld" in message
        assert "<h1>Hello</h1><p>World</p>" in message
        assert _REPLY_TO in message
        assert _EMAIL_FROM in message

    @pytest.mark.unit
    async def test_wraps_smtp_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_smtp_env(monkeypatch)
        smtp = _RecordingSMTP("smtp.test", 2525, timeout=10)

        def _failing_login(user: str, password: str) -> None:
            raise RuntimeError("bad login")

        smtp.login = _failing_login

        with (
            patch("teleclaude.services.email.asyncio.to_thread", new=AsyncMock(side_effect=_run_sync)),
            patch("teleclaude.services.email.smtplib.SMTP", return_value=smtp),
        ):
            with pytest.raises(RuntimeError, match="SMTP delivery failed: bad login"):
                await send_email(_RECIPIENT, "Subject", "<p>Hello</p>")
