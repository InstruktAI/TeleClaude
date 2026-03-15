"""Characterization tests for teleclaude.invite."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from teleclaude import invite

pytestmark = pytest.mark.unit


class _FakeAsyncResponse:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Mapping[str, object]:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeAsyncResponse:
        self.calls.append((url, headers))
        return _FakeAsyncResponse(self.payload)


class TestGenerateInviteLinks:
    def test_builds_links_for_all_available_platforms(self) -> None:
        links = invite.generate_invite_links("token-123", "teleclaudebot", "999", "15551212")

        assert links == {
            "telegram": "https://t.me/teleclaudebot?start=token-123",
            "discord": "https://discord.com/users/999",
            "whatsapp": "https://wa.me/15551212?text=token-123",
        }


class TestScaffoldPersonalWorkspace:
    def test_creates_person_workspace_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(invite, "_PEOPLE_DIR", tmp_path / "people")

        person_path = invite.scaffold_personal_workspace("morris")

        assert person_path == tmp_path / "people" / "morris"
        assert (person_path / "AGENTS.master.md").exists()
        assert (person_path / "teleclaude.yml").exists()


class TestResolveBots:
    @pytest.mark.asyncio
    async def test_resolve_telegram_bot_username_reads_get_me_payload(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret")
        fake_client = _FakeAsyncClient({"ok": True, "result": {"username": "teleclaudebot"}})
        monkeypatch.setattr(invite.httpx, "AsyncClient", lambda timeout: fake_client)

        username = await invite.resolve_telegram_bot_username()

        assert username == "teleclaudebot"
        assert fake_client.calls[0][0].endswith("/botsecret/getMe")

    @pytest.mark.asyncio
    async def test_resolve_discord_bot_user_id_reads_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret")
        fake_client = _FakeAsyncClient({"id": "123456"})
        monkeypatch.setattr(invite.httpx, "AsyncClient", lambda timeout: fake_client)

        user_id = await invite.resolve_discord_bot_user_id()

        assert user_id == "123456"
        assert fake_client.calls[0][1] == {"Authorization": "Bot secret"}


class TestSendInviteEmail:
    @pytest.mark.asyncio
    async def test_prints_links_when_smtp_is_not_configured(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("BREVO_SMTP_USER", raising=False)

        await invite.send_invite_email(
            name="Morris",
            email="morris@example.com",
            links={"telegram": "https://t.me/demo", "discord": None, "whatsapp": None},
        )

        output = capsys.readouterr().out
        assert "Invite Links for Morris" in output
        assert "Telegram: https://t.me/demo" in output
