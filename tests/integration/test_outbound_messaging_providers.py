"""Functional bindings for the outbound messaging provider file-attachment capabilities.

Binds UC-MP9 (Discord DM with file attachment) and UC-MP10 (email with file
attachment) of ``project/spec/feature/integration/outbound-messaging-providers``
against the real provider helpers, faking only the process boundary (the Discord
HTTP client, the SMTP connection).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from email import message_from_string

import pytest

import teleclaude.services.discord as discord_mod
import teleclaude.services.email as email_mod
from teleclaude.services.discord import send_discord_dm
from teleclaude.services.email import send_email

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/integration/outbound-messaging-providers"
_DM_CHANNEL_ENDPOINT_SUFFIX = "/users/@me/channels"
_MESSAGE_TEXT = "Caption text"
_ATTACHMENT_FILENAME = "report.pdf"
_MIME_TYPE_MIXED = "multipart/mixed"
_MIME_TYPE_ALTERNATIVE = "multipart/alternative"


# guard: loose-dict-func - mirrors httpx Response.json()
class _FakeHttpResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, object]:
        return self._payload


# guard: loose-dict-func - mirrors httpx client.post kwargs (json=, data=, files=)
@dataclass
class _RecordedCall:
    url: str
    json_body: dict[str, object] | None
    data: dict[str, object] | None
    files: dict[str, tuple[str, object, str]] | None


class _FakeDiscordClient:
    """Records every POST the DM-with-file flow issues."""

    def __init__(self) -> None:
        self.calls: list[_RecordedCall] = []

    # guard: loose-dict-func - mirrors httpx client.post kwargs (json=, data=, files=)
    async def post(
        self,
        url: str,
        *,
        json: dict[str, object] | None = None,
        data: dict[str, object] | None = None,
        files: dict[str, tuple[str, object, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeHttpResponse:
        del headers
        self.calls.append(_RecordedCall(url=url, json_body=json, data=data, files=files))
        if url.endswith(_DM_CHANNEL_ENDPOINT_SUFFIX):
            return _FakeHttpResponse(200, {"id": "channel-1"})
        return _FakeHttpResponse(200, {"id": "message-1"})

    async def aclose(self) -> None:
        return None


@pytest.mark.spec(_SPEC, "UC-MP9")
async def test_discord_dm_with_file_uploads_multipart_with_content(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    fake_client = _FakeDiscordClient()
    monkeypatch.setattr(discord_mod.httpx, "AsyncClient", lambda timeout=None: fake_client)

    file_path = tmp_path / _ATTACHMENT_FILENAME
    file_path.write_bytes(b"%PDF-1.4 fake report")

    message_id = await send_discord_dm("user-id-1", _MESSAGE_TEXT, str(file_path))

    assert message_id
    create_call, message_call = fake_client.calls
    assert create_call.url.endswith(_DM_CHANNEL_ENDPOINT_SUFFIX)
    files = message_call.files
    assert files is not None
    assert files["files[0]"][0] == _ATTACHMENT_FILENAME
    data = message_call.data
    assert data is not None
    payload = json.loads(str(data["payload_json"]))
    assert payload["content"] == _MESSAGE_TEXT


async def test_discord_dm_with_missing_file_raises_not_found(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")

    with pytest.raises(FileNotFoundError):
        await send_discord_dm("user-id-1", "hi", "/no/such/report.pdf")


async def test_discord_dm_with_directory_as_file_raises_invalid_argument(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")

    with pytest.raises(ValueError, match="Not a file"):
        await send_discord_dm("user-id-1", "hi", str(tmp_path))


def _enable_email(monkeypatch) -> None:
    monkeypatch.setattr(email_mod.config.email, "enabled", True)
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_KEY", "secret")
    monkeypatch.setenv("EMAIL_FROM", "TeleClaude <noreply@example.com>")


def _fake_smtp(monkeypatch) -> list[tuple[str, str, str]]:
    sent: list[tuple[str, str, str]] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            del host, port, timeout

        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *exc_info: object) -> None:
            del exc_info

        def starttls(self) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            del user, password

        def sendmail(self, sender: str, to: str, message: str) -> None:
            sent.append((sender, to, message))

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    return sent


@pytest.mark.spec(_SPEC, "UC-MP10")
async def test_email_with_attachment_wraps_alternative_in_mixed(monkeypatch, tmp_path) -> None:
    _enable_email(monkeypatch)
    sent = _fake_smtp(monkeypatch)

    attachment_path = tmp_path / _ATTACHMENT_FILENAME
    attachment_path.write_bytes(b"%PDF-1.4 fake report")

    await send_email("alice@example.com", "Subject", "<p>hi</p>", attachment=str(attachment_path))

    assert len(sent) == 1
    _, _, raw_message = sent[0]
    parsed = message_from_string(raw_message)
    assert parsed.get_content_type() == _MIME_TYPE_MIXED
    parts = list(parsed.walk())
    assert any(part.get_content_type() == _MIME_TYPE_ALTERNATIVE for part in parts)
    attachment_parts = [part for part in parts if part.get_filename() == _ATTACHMENT_FILENAME]
    assert len(attachment_parts) == 1


async def test_email_without_attachment_stays_plain_alternative(monkeypatch) -> None:
    _enable_email(monkeypatch)
    sent = _fake_smtp(monkeypatch)

    await send_email("alice@example.com", "Subject", "<p>hi</p>")

    assert len(sent) == 1
    _, _, raw_message = sent[0]
    parsed = message_from_string(raw_message)
    assert parsed.get_content_type() == _MIME_TYPE_ALTERNATIVE


async def test_email_with_missing_attachment_raises_not_found(monkeypatch) -> None:
    _enable_email(monkeypatch)

    with pytest.raises(FileNotFoundError):
        await send_email("alice@example.com", "Subject", "<p>hi</p>", attachment="/no/such/report.pdf")


async def test_email_with_directory_as_attachment_raises_invalid_argument(monkeypatch, tmp_path) -> None:
    _enable_email(monkeypatch)

    with pytest.raises(ValueError, match="Not a file"):
        await send_email("alice@example.com", "Subject", "<p>hi</p>", attachment=str(tmp_path))
