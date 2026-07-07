"""Functional bindings for WhatsApp inbound conversation routing.

Binds ``project/spec/feature/integration/whatsapp-inbound-conversation-routing``
(UC-WI1..UC-WI10) to the rewired handler in ``teleclaude.hooks.whatsapp_handler``
(handler-boundary, UC-WI1..UC-WI8 — in-process session resolution through the
shared core inbound seam, dispatch through the WhatsApp UI adapter's public
dispatch path, and inbound media fetch consolidated onto
``teleclaude.services.whatsapp``) and to
``teleclaude.hooks.normalizers.whatsapp`` (normalizer-boundary confirm-no-change,
UC-WI9..UC-WI10, unaffected by this rewire).
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.config.loader as loader_mod
import teleclaude.core.identity as identity_mod
import teleclaude.hooks.whatsapp_handler as whatsapp_handler_mod
import teleclaude.services.whatsapp as whatsapp_service_mod
from teleclaude.adapters.whatsapp_adapter import WhatsAppAdapter
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.command_service import CommandService
from teleclaude.core.db import Db
from teleclaude.core.models import Session, SessionLaunchKind
from teleclaude.core.origins import InputOrigin
from teleclaude.hooks.normalizers.whatsapp import normalize_whatsapp_webhook
from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.types.commands import CreateSessionCommand, HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/integration/whatsapp-inbound-conversation-routing"
_PHONE = "31612345678"
_DEFAULT_AGENT = "claude"
_THINKING_MODE_SLOW = "slow"
_MESSAGE_TEXT_1 = "hello"
_MESSAGE_TEXT_2 = "again"
_MESSAGE_ID_1 = "wamid.1"
_MESSAGE_ID_2 = "wamid.2"
_EVENT_TIMESTAMP = "2024-01-01T00:00:00+00:00"
_EXISTING_SESSION_ID = "existing-session"
_TYPE_MESSAGE_VOICE = "message.voice"
_TYPE_MESSAGE_AUDIO = "message.audio"


@dataclass
class _FakeDb:
    sessions: dict[str, Session] = field(default_factory=dict)

    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def get_sessions_by_origin_metadata(
        self,
        adapter_type: str,
        metadata_key: str,
        metadata_value: object,
        include_closed: bool = False,
    ) -> list[Session]:
        del include_closed
        return [
            session
            for session in self.sessions.values()
            if session.get_origin_section(adapter_type).get(metadata_key) == metadata_value
        ]

    async def update_origin_metadata(
        self,
        session_id: str,
        platform: str,
        section_updates: dict[str, object],  # guard: loose-dict - Per-platform JSON section
    ) -> None:
        session = self.sessions[session_id]
        section = dict(session.get_origin_section(platform))
        section.update(section_updates)
        origin_metadata = dict(session.origin_metadata)
        origin_metadata[platform] = section
        self.sessions[session_id] = replace(session, origin_metadata=origin_metadata)


class _FakeAdapterClient:
    """Minimal stand-in for AdapterClient's pre/post command hooks."""

    async def pre_handle_command(self, session: Session, origin: str) -> None:
        del session, origin

    async def post_handle_command(self, session: Session, message_id: str, origin: str) -> None:
        del session, message_id, origin


class _CommandService:
    def __init__(self, db: _FakeDb, *, adapter: object | None, empty_session_id: bool = False) -> None:
        self._db = db
        self._empty_session_id = empty_session_id
        adapters = {"whatsapp": adapter} if adapter is not None else {}
        self.client = SimpleNamespace(adapters=adapters)
        self.create_calls: list[CreateSessionCommand] = []
        self.process_calls: list[ProcessMessageCommand] = []
        self.voice_calls: list[HandleVoiceCommand] = []
        self.file_calls: list[HandleFileCommand] = []

    async def create_session(self, command: CreateSessionCommand) -> dict[str, str]:
        self.create_calls.append(command)
        if self._empty_session_id:
            return {"session_id": ""}
        session_id = f"session-{len(self.create_calls)}"
        session = Session(
            session_id=session_id,
            computer_name="local",
            tmux_session_name=session_id,
            title="WhatsApp",
            origin_metadata={"whatsapp": dict(command.origin_metadata or {})},
        )
        self._db.sessions[session_id] = session
        return {"session_id": session_id}

    async def process_message(self, command: ProcessMessageCommand) -> None:
        self.process_calls.append(command)

    async def handle_voice(self, command: HandleVoiceCommand) -> None:
        self.voice_calls.append(command)

    async def handle_file(self, command: HandleFileCommand) -> None:
        self.file_calls.append(command)


class _FakeMediaHttpResponse:
    def __init__(
        self,
        *,
        json_data: dict[str, object] | None = None,  # guard: loose-dict - mirrors httpx Response.json()
        content: bytes = b"",
    ) -> None:
        self._json_data = json_data
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:  # guard: loose-dict - mirrors httpx Response.json()
        assert self._json_data is not None
        return self._json_data


class _FakeMediaHttpClient:
    """Fakes the two-request Meta Graph media fetch (lookup URL, then fetch bytes)."""

    def __init__(self, calls: list[str], media_download_url: str, media_bytes: bytes) -> None:
        self._calls = calls
        self._media_download_url = media_download_url
        self._media_bytes = media_bytes

    async def __aenter__(self) -> _FakeMediaHttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> _FakeMediaHttpResponse:
        del headers
        self._calls.append(url)
        if len(self._calls) == 1:
            return _FakeMediaHttpResponse(json_data={"url": self._media_download_url})
        return _FakeMediaHttpResponse(content=self._media_bytes)


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    adapter: object | None,
    empty_session_id: bool = False,
) -> tuple[_FakeDb, _CommandService]:
    fake_db = _FakeDb()
    service = _CommandService(fake_db, adapter=adapter, empty_session_id=empty_session_id)
    monkeypatch.setattr(whatsapp_handler_mod, "db", fake_db)
    monkeypatch.setattr(whatsapp_handler_mod, "get_command_service", lambda: service)
    monkeypatch.setattr(whatsapp_handler_mod, "get_default_agent", lambda: _DEFAULT_AGENT)
    monkeypatch.setattr(whatsapp_handler_mod, "get_session_output_dir", lambda session_id: tmp_path)
    monkeypatch.setattr(whatsapp_handler_mod.config.computer, "help_desk_dir", str(tmp_path / "help-desk"))
    monkeypatch.setattr(whatsapp_handler_mod.config.whatsapp, "access_token", "test-token")
    monkeypatch.setattr(whatsapp_handler_mod.config.whatsapp, "api_version", "v21.0")
    return fake_db, service


def _install_media_fetch_fake(monkeypatch: pytest.MonkeyPatch, *, media_bytes: bytes) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        whatsapp_service_mod.httpx,
        "AsyncClient",
        lambda timeout=None: _FakeMediaHttpClient(calls, "https://cdn.example.com/media-blob", media_bytes),
    )
    return calls


def _text_event(*, message_id: str = _MESSAGE_ID_1, text: str = _MESSAGE_TEXT_1) -> HookEvent:
    return HookEvent(
        source="whatsapp",
        type="message.text",
        timestamp=_EVENT_TIMESTAMP,
        properties={"phone_number": _PHONE, "message_id": message_id, "text": text},
    )


def _media_event(*, event_type: str, media_id: str, mime_type: str, message_id: str = _MESSAGE_ID_2) -> HookEvent:
    return HookEvent(
        source="whatsapp",
        type=event_type,
        timestamp=_EVENT_TIMESTAMP,
        properties={"phone_number": _PHONE, "message_id": message_id, "media_id": media_id, "mime_type": mime_type},
    )


@pytest.fixture
async def real_command_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncGenerator[Db, None]:
    """Wire the real create-session boundary: a real in-memory DB and a real,
    hermetically-empty-config ``IdentityResolver`` — so unknown-phone-number
    session creation exercises the actual identity/help-desk-jailing contract
    (``core/command_handlers/_session.py``) instead of a hand-rolled fake.
    """
    test_db = Db(":memory:")
    await test_db.initialize()

    db_mod = importlib.import_module("teleclaude.core.db")
    monkeypatch.setattr(db_mod, "db", test_db)
    session_handler_mod = importlib.import_module("teleclaude.core.command_handlers._session")
    for mod in (session_handler_mod, whatsapp_handler_mod):
        if hasattr(mod, "db"):
            monkeypatch.setattr(mod, "db", test_db)

    # Hermetic, empty people config — an unregistered WhatsApp phone number
    # must resolve through the REAL IdentityResolver's whatsapp branch to
    # "customer", not through whatever config happens to be on this machine.
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    global_path = tmp_path / "teleclaude.yml"
    global_path.write_text("people: []\n", encoding="utf-8")
    monkeypatch.setattr(loader_mod, "GLOBAL_CONFIG_PATH", global_path)
    monkeypatch.setattr(loader_mod, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity_mod, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity_mod, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(identity_mod, "_GLOBAL_CONFIG_PATH", global_path)
    real_resolver = identity_mod.IdentityResolver()
    monkeypatch.setattr(session_handler_mod, "get_identity_resolver", lambda: real_resolver)

    monkeypatch.setattr(whatsapp_handler_mod.config.computer, "help_desk_dir", str(tmp_path / "help-desk"))
    monkeypatch.setattr(whatsapp_handler_mod, "get_default_agent", lambda: _DEFAULT_AGENT)

    def _discard_background_task(task: object, name: str | None = None) -> None:
        del name
        close = getattr(task, "close", None)
        if callable(close):
            close()

    async def _noop_bootstrap(session_id: str, launch_intent: object = None) -> None:
        del session_id, launch_intent

    cmd_service = CommandService(
        client=SimpleNamespace(adapters={}),
        start_polling=AsyncMock(),
        execute_terminal_command=AsyncMock(),
        queue_background_task=_discard_background_task,
        bootstrap_session=_noop_bootstrap,
    )
    # Scope this harness to the real create-session boundary under test — the
    # downstream process-message dispatch (tmux polling, agent output) is out
    # of scope here and is already covered by the handler-boundary tests above.
    monkeypatch.setattr(cmd_service, "process_message", AsyncMock())
    monkeypatch.setattr(whatsapp_handler_mod, "get_command_service", lambda: cmd_service)

    yield test_db
    await test_db.close()


@pytest.mark.spec(_SPEC, "UC-WI1")
async def test_unknown_phone_number_resolves_to_customer_role_via_real_identity_and_session_create(
    real_command_service: Db,
) -> None:
    await whatsapp_handler_mod.handle_whatsapp_event(_text_event())

    created = await real_command_service.get_sessions_by_origin_metadata("whatsapp", "phone_number", _PHONE)
    assert len(created) == 1
    session = created[0]
    assert session.human_role == HUMAN_ROLE_CUSTOMER
    assert session.active_agent == _DEFAULT_AGENT
    assert session.thinking_mode == _THINKING_MODE_SLOW


@pytest.mark.spec(_SPEC, "UC-WI1")
async def test_text_message_creates_session_in_process_and_dispatches_process_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = WhatsAppAdapter(client=_FakeAdapterClient())
    fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=adapter)

    # No HTTP loopback client exists on the rewired module at all.
    assert not hasattr(whatsapp_handler_mod, "TelecAPIClient")

    await whatsapp_handler_mod.handle_whatsapp_event(_text_event(text=_MESSAGE_TEXT_1))

    assert len(service.create_calls) == 1
    created = service.create_calls[0]
    assert created.origin == InputOrigin.WHATSAPP.value
    assert created.origin_metadata == {"phone_number": _PHONE, "platform": "whatsapp"}
    assert created.launch_intent is not None
    assert created.launch_intent.kind == SessionLaunchKind.AGENT
    assert created.launch_intent.agent == _DEFAULT_AGENT
    assert created.launch_intent.thinking_mode == _THINKING_MODE_SLOW

    assert len(service.process_calls) == 1
    process_cmd = service.process_calls[0]
    assert process_cmd.text == _MESSAGE_TEXT_1
    assert process_cmd.origin == InputOrigin.WHATSAPP.value
    assert process_cmd.actor_id == f"whatsapp:{_PHONE}"
    assert process_cmd.actor_name == _PHONE

    session_id = next(iter(fake_db.sessions))
    wa_section = fake_db.sessions[session_id].get_origin_section("whatsapp")
    assert wa_section["phone_number"] == _PHONE
    assert wa_section["last_received_message_id"] == _MESSAGE_ID_1
    assert wa_section["last_customer_message_at"] == _EVENT_TIMESTAMP


@pytest.mark.spec(_SPEC, "UC-WI2")
async def test_existing_session_is_reused_for_same_phone_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = WhatsAppAdapter(client=_FakeAdapterClient())
    fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=adapter)
    existing = Session(
        session_id=_EXISTING_SESSION_ID,
        computer_name="local",
        tmux_session_name=_EXISTING_SESSION_ID,
        title="WhatsApp",
        origin_metadata={"whatsapp": {"phone_number": _PHONE}},
    )
    fake_db.sessions[existing.session_id] = existing

    await whatsapp_handler_mod.handle_whatsapp_event(_text_event(message_id=_MESSAGE_ID_2, text=_MESSAGE_TEXT_2))

    assert len(service.create_calls) == 0
    assert len(service.process_calls) == 1
    assert service.process_calls[0].session_id == _EXISTING_SESSION_ID
    wa_section = fake_db.sessions[_EXISTING_SESSION_ID].get_origin_section("whatsapp")
    assert wa_section["last_received_message_id"] == _MESSAGE_ID_2


@pytest.mark.spec(_SPEC, "UC-WI3")
async def test_voice_message_downloads_ogg_into_voice_subdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = WhatsAppAdapter(client=_FakeAdapterClient())
    _fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=adapter)
    calls = _install_media_fetch_fake(monkeypatch, media_bytes=b"OGGDATA")

    # The spec's exact Given input: WhatsApp voice notes report the codecs
    # parameter, which mimetypes.guess_extension does not strip.
    mime_type = "audio/ogg; codecs=opus"
    event = _media_event(event_type="message.voice", media_id="abcdef123456", mime_type=mime_type)
    await whatsapp_handler_mod.handle_whatsapp_event(event)

    assert len(calls) == 2
    voice_dir = tmp_path / "voice"
    written = list(voice_dir.glob(f"{_PHONE}_*_abcdef123456.ogg"))
    assert len(written) == 1
    assert written[0].read_bytes() == b"OGGDATA"

    assert len(service.voice_calls) == 1
    voice_cmd = service.voice_calls[0]
    assert voice_cmd.file_path == str(written[0])
    assert voice_cmd.origin == InputOrigin.WHATSAPP.value
    assert voice_cmd.actor_id == f"whatsapp:{_PHONE}"


@pytest.mark.spec(_SPEC, "UC-WI4")
async def test_image_message_downloads_into_photos_as_handle_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = WhatsAppAdapter(client=_FakeAdapterClient())
    _fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=adapter)
    _install_media_fetch_fake(monkeypatch, media_bytes=b"JPEGDATA")

    event = _media_event(event_type="message.image", media_id="img-1", mime_type="image/jpeg")
    await whatsapp_handler_mod.handle_whatsapp_event(event)

    photos_dir = tmp_path / "photos"
    written = list(photos_dir.glob(f"{_PHONE}_*_img-1.jpg"))
    assert len(written) == 1
    assert len(service.file_calls) == 1
    assert service.file_calls[0].filename == written[0].name


@pytest.mark.spec(_SPEC, "UC-WI5")
async def test_document_message_downloads_into_files_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = WhatsAppAdapter(client=_FakeAdapterClient())
    _fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=adapter)
    _install_media_fetch_fake(monkeypatch, media_bytes=b"PDFDATA")

    event = _media_event(event_type="message.document", media_id="doc-1", mime_type="application/pdf")
    await whatsapp_handler_mod.handle_whatsapp_event(event)

    files_dir = tmp_path / "files"
    written = list(files_dir.glob(f"{_PHONE}_*_doc-1.pdf"))
    assert len(written) == 1
    assert len(service.file_calls) == 1


@pytest.mark.spec(_SPEC, "UC-WI6")
async def test_missing_whatsapp_adapter_falls_back_to_direct_handler_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=None)

    await whatsapp_handler_mod.handle_whatsapp_event(_text_event())

    assert service.client.adapters == {}
    assert len(service.process_calls) == 1


@pytest.mark.spec(_SPEC, "UC-WI7")
async def test_missing_phone_number_drops_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=None)

    event = HookEvent(
        source="whatsapp",
        type="message.text",
        timestamp="2024-01-01T00:00:00+00:00",
        properties={"phone_number": "", "message_id": "wamid.1", "text": "hello"},
    )
    await whatsapp_handler_mod.handle_whatsapp_event(event)

    assert len(service.create_calls) == 0
    assert len(service.process_calls) == 0


@pytest.mark.spec(_SPEC, "UC-WI8")
async def test_empty_created_session_id_drops_event_silently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_db, service = _install_fakes(monkeypatch, tmp_path, adapter=None, empty_session_id=True)

    await whatsapp_handler_mod.handle_whatsapp_event(_text_event())

    assert len(service.create_calls) == 1
    assert len(service.process_calls) == 0
    assert fake_db.sessions == {}


def _webhook_message_payload(message: dict[str, object]) -> dict[str, object]:  # guard: loose-dict - webhook payload
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


@pytest.mark.spec(_SPEC, "UC-WI9")
def test_unix_seconds_timestamp_normalizes_to_utc_iso8601() -> None:
    payload = _webhook_message_payload(
        {"id": "wamid.1", "from": _PHONE, "type": "text", "timestamp": "1700000000", "text": {"body": "hi"}}
    )
    events = normalize_whatsapp_webhook(payload, {})

    assert len(events) == 1
    assert events[0].timestamp == datetime.fromtimestamp(1700000000, tz=UTC).isoformat()


@pytest.mark.spec(_SPEC, "UC-WI9")
def test_missing_timestamp_falls_back_to_current_utc_time() -> None:
    payload = _webhook_message_payload({"id": "wamid.1", "from": _PHONE, "type": "text", "text": {"body": "hi"}})

    before = datetime.now(UTC)
    events = normalize_whatsapp_webhook(payload, {})
    after = datetime.now(UTC)

    parsed = datetime.fromisoformat(events[0].timestamp)
    assert before <= parsed <= after


@pytest.mark.spec(_SPEC, "UC-WI10")
def test_voice_type_or_ogg_mime_classifies_as_message_voice() -> None:
    voice_payload = _webhook_message_payload(
        {"id": "wamid.1", "from": _PHONE, "type": "voice", "audio": {"mime_type": "audio/ogg; codecs=opus"}}
    )
    ogg_audio_payload = _webhook_message_payload(
        {"id": "wamid.2", "from": _PHONE, "type": "audio", "audio": {"mime_type": "audio/ogg; codecs=opus"}}
    )

    assert normalize_whatsapp_webhook(voice_payload, {})[0].type == _TYPE_MESSAGE_VOICE
    assert normalize_whatsapp_webhook(ogg_audio_payload, {})[0].type == _TYPE_MESSAGE_VOICE


@pytest.mark.spec(_SPEC, "UC-WI10")
def test_non_ogg_audio_classifies_as_message_audio() -> None:
    payload = _webhook_message_payload(
        {"id": "wamid.1", "from": _PHONE, "type": "audio", "audio": {"mime_type": "audio/mp3"}}
    )

    assert normalize_whatsapp_webhook(payload, {})[0].type == _TYPE_MESSAGE_AUDIO
