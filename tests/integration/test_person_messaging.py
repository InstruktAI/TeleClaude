"""Behavioral coverage for the person-addressed messaging service.

Binds the PRD success criteria (SC-1, SC-2, SC-4, SC-5, SC-7 of
``telec-message-primitive``) against ``teleclaude.core.person_messaging``, the
service layer the ``telec message`` route dispatches through. No feature spec
exists for this command-surface-refinement todo (Category B), so these tests
carry no ``@pytest.mark.spec`` marker — they assert the PRD contract directly.
Only the process boundary (the outbound provider send calls) is faked.
"""

from __future__ import annotations

import pytest

import teleclaude.core.person_messaging as person_messaging_mod
from teleclaude.config.schema import (
    CredsConfig,
    DiscordCreds,
    GlobalConfig,
    MessagingChannel,
    PersonConfig,
    PersonEntry,
    TelegramCreds,
    WhatsAppCreds,
)
from teleclaude.core.person_messaging import (
    ChannelCapabilityError,
    ChannelCredentialError,
    PersonNotFoundError,
    send_person_message,
)

pytestmark = pytest.mark.functional

_SLUG = "alex"
_EMAIL = "alex@example.com"
_MESSAGE_TEXT = "hi"
_CAPTION_TEXT = "caption"
_BODY_TEXT = "body text"
_CUSTOM_SUBJECT = "Custom subject"
_IGNORED_SUBJECT = "ignored"
_TELEGRAM_CHAT_ID = "chat-1"
_DISCORD_USER_ID = "user-1"
_WHATSAPP_PHONE = "31612345678"
_ATTACHMENT_FILENAME = "report.pdf"


def _person() -> PersonEntry:
    return PersonEntry(name="Alex", email=_EMAIL, slug=_SLUG, role="member")


def _install(monkeypatch: pytest.MonkeyPatch, *, person_config: PersonConfig, sent: list[tuple[object, ...]]) -> None:
    async def _fake_telegram(chat_id: str, content: str, file: str | None = None) -> str:
        sent.append(("telegram", chat_id, content, file))
        return "tg-message-id"

    async def _fake_discord(user_id: str, content: str, file: str | None = None) -> str:
        sent.append(("discord", user_id, content, file))
        return "discord-message-id"

    async def _fake_whatsapp(
        phone_number: str, content: str, *, phone_number_id: str, access_token: str, api_version: str
    ) -> str:
        del phone_number_id, access_token, api_version
        sent.append(("whatsapp", phone_number, content, None))
        return "whatsapp-message-id"

    async def _fake_email(
        to: str, subject: str, html_body: str, text_body: str | None = None, attachment: str | None = None
    ) -> None:
        del html_body, text_body
        sent.append(("email", to, subject, attachment))

    monkeypatch.setattr(person_messaging_mod, "load_global_config", lambda: GlobalConfig(people=[_person()]))
    monkeypatch.setattr(person_messaging_mod, "load_person_config_for_entry", lambda person, people_dir: person_config)
    monkeypatch.setattr(person_messaging_mod, "send_telegram_dm", _fake_telegram)
    monkeypatch.setattr(person_messaging_mod, "send_discord_dm", _fake_discord)
    monkeypatch.setattr(person_messaging_mod, "send_whatsapp_message", _fake_whatsapp)
    monkeypatch.setattr(person_messaging_mod, "send_email", _fake_email)


async def test_default_channel_resolves_to_person_preferred_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    person_config = PersonConfig(
        preferred_channel=MessagingChannel.DISCORD,
        creds=CredsConfig(discord=DiscordCreds(user_id=_DISCORD_USER_ID)),
    )
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)

    outcome = await send_person_message(_SLUG, _MESSAGE_TEXT)

    assert outcome.channel is MessagingChannel.DISCORD
    assert sent == [("discord", _DISCORD_USER_ID, _MESSAGE_TEXT, None)]


async def test_explicit_channel_overrides_preferred_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    person_config = PersonConfig(
        preferred_channel=MessagingChannel.DISCORD,
        creds=CredsConfig(
            discord=DiscordCreds(user_id=_DISCORD_USER_ID),
            telegram=TelegramCreds(user_name="alex", user_id=1, chat_id=_TELEGRAM_CHAT_ID),
        ),
    )
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)

    outcome = await send_person_message(_SLUG, _MESSAGE_TEXT, channel=MessagingChannel.TELEGRAM)

    assert outcome.channel is MessagingChannel.TELEGRAM
    assert sent == [("telegram", _TELEGRAM_CHAT_ID, _MESSAGE_TEXT, None)]


async def test_file_attachment_delivers_as_caption_on_discord(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    person_config = PersonConfig(
        preferred_channel=MessagingChannel.DISCORD,
        creds=CredsConfig(discord=DiscordCreds(user_id=_DISCORD_USER_ID)),
    )
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)
    file_path = tmp_path / _ATTACHMENT_FILENAME
    file_path.write_bytes(b"data")

    await send_person_message(_SLUG, _CAPTION_TEXT, file=str(file_path))

    assert sent == [("discord", _DISCORD_USER_ID, _CAPTION_TEXT, str(file_path))]


async def test_email_channel_delivers_attachment_and_default_subject(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    person_config = PersonConfig(preferred_channel=MessagingChannel.EMAIL)
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)
    file_path = tmp_path / _ATTACHMENT_FILENAME
    file_path.write_bytes(b"data")

    await send_person_message(_SLUG, _BODY_TEXT, file=str(file_path))

    assert sent == [("email", _EMAIL, person_messaging_mod.DEFAULT_EMAIL_SUBJECT, str(file_path))]


async def test_email_channel_uses_explicit_subject_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    person_config = PersonConfig(preferred_channel=MessagingChannel.EMAIL)
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)

    await send_person_message(_SLUG, _BODY_TEXT, subject=_CUSTOM_SUBJECT)

    assert sent == [("email", _EMAIL, _CUSTOM_SUBJECT, None)]


async def test_subject_is_inert_on_a_non_email_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    person_config = PersonConfig(
        preferred_channel=MessagingChannel.TELEGRAM,
        creds=CredsConfig(telegram=TelegramCreds(user_name="alex", user_id=1, chat_id=_TELEGRAM_CHAT_ID)),
    )
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)

    outcome = await send_person_message(_SLUG, _MESSAGE_TEXT, subject=_IGNORED_SUBJECT)

    assert outcome.channel is MessagingChannel.TELEGRAM
    assert sent == [("telegram", _TELEGRAM_CHAT_ID, _MESSAGE_TEXT, None)]


async def test_file_to_a_whatsapp_recipient_is_refused_without_sending(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    person_config = PersonConfig(
        preferred_channel=MessagingChannel.WHATSAPP,
        creds=CredsConfig(whatsapp=WhatsAppCreds(phone_number=_WHATSAPP_PHONE)),
    )
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)
    file_path = tmp_path / _ATTACHMENT_FILENAME
    file_path.write_bytes(b"data")

    with pytest.raises(ChannelCapabilityError):
        await send_person_message(_SLUG, _MESSAGE_TEXT, file=str(file_path))
    assert sent == []


async def test_unresolvable_slug_raises_person_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(person_messaging_mod, "load_global_config", lambda: GlobalConfig(people=[]))

    with pytest.raises(PersonNotFoundError):
        await send_person_message("nobody", _MESSAGE_TEXT)


async def test_missing_credential_for_resolved_channel_raises_distinct_error_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_config = PersonConfig(preferred_channel=MessagingChannel.DISCORD)  # no discord creds configured
    sent: list[tuple[object, ...]] = []
    _install(monkeypatch, person_config=person_config, sent=sent)

    with pytest.raises(ChannelCredentialError):
        await send_person_message(_SLUG, _MESSAGE_TEXT)
    assert sent == []
