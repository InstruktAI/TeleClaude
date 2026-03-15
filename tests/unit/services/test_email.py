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


class TestSendEmail:
    @pytest.mark.unit
    async def test_requires_brevo_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BREVO_SMTP_USER", raising=False)
        monkeypatch.delenv("BREVO_SMTP_PASS", raising=False)
        monkeypatch.delenv("BREVO_SENDER_EMAIL", raising=False)

        with pytest.raises(ValueError, match="Missing required Brevo SMTP credentials"):
            await send_email("person@example.com", "Subject", "<p>Hello</p>")

    @pytest.mark.unit
    async def test_builds_plain_text_fallback_from_html(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BREVO_SMTP_USER", "user")
        monkeypatch.setenv("BREVO_SMTP_PASS", "pass")
        monkeypatch.setenv("BREVO_SENDER_EMAIL", "sender@example.com")
        monkeypatch.setenv("BREVO_SENDER_NAME", "TeleClaude Test")
        smtp = _RecordingSMTP("smtp.test", 2525, timeout=10)

        with (
            patch("teleclaude.services.email.asyncio.to_thread", new=AsyncMock(side_effect=_run_sync)),
            patch("teleclaude.services.email.smtplib.SMTP", return_value=smtp),
        ):
            await send_email(
                "person@example.com",
                "Subject",
                "<h1>Hello</h1><p>World</p>",
                smtp_host="smtp.test",
                smtp_port=2525,
            )

        assert smtp.started_tls is True
        assert smtp.login_args == ("user", "pass")
        assert smtp.sendmail_args is not None
        assert smtp.sendmail_args[0] == "sender@example.com"
        assert smtp.sendmail_args[1] == "person@example.com"
        assert "HelloWorld" in smtp.sendmail_args[2]
        assert "<h1>Hello</h1><p>World</p>" in smtp.sendmail_args[2]

    @pytest.mark.unit
    async def test_wraps_smtp_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BREVO_SMTP_USER", "user")
        monkeypatch.setenv("BREVO_SMTP_PASS", "pass")
        monkeypatch.setenv("BREVO_SENDER_EMAIL", "sender@example.com")
        smtp = _RecordingSMTP("smtp.test", 2525, timeout=10)

        def _failing_login(user: str, password: str) -> None:
            raise RuntimeError("bad login")

        smtp.login = _failing_login

        with (
            patch("teleclaude.services.email.asyncio.to_thread", new=AsyncMock(side_effect=_run_sync)),
            patch("teleclaude.services.email.smtplib.SMTP", return_value=smtp),
        ):
            with pytest.raises(RuntimeError, match="SMTP delivery failed: bad login"):
                await send_email("person@example.com", "Subject", "<p>Hello</p>")
