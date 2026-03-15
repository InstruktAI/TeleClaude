"""Characterization tests for teleclaude.core.models._adapter."""

from __future__ import annotations

import json

import pytest

from teleclaude.core.models._adapter import (
    AdapterType,
    DiscordAdapterMetadata,
    RedisTransportMetadata,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
    TransportAdapterMetadata,
    UiAdapterMetadata,
    WhatsAppAdapterMetadata,
)


class TestAdapterType:
    @pytest.mark.unit
    def test_telegram_value(self):
        assert AdapterType.TELEGRAM.value == "telegram"

    @pytest.mark.unit
    def test_discord_value(self):
        assert AdapterType.DISCORD.value == "discord"

    @pytest.mark.unit
    def test_whatsapp_value(self):
        assert AdapterType.WHATSAPP.value == "whatsapp"

    @pytest.mark.unit
    def test_redis_value(self):
        assert AdapterType.REDIS.value == "redis"


class TestTelegramAdapterMetadata:
    @pytest.mark.unit
    def test_default_fields_are_none_or_falsy(self):
        m = TelegramAdapterMetadata()
        assert m.topic_id is None
        assert m.output_message_id is None
        assert m.footer_message_id is None
        assert m.output_suppressed is False
        assert m.parse_mode is None
        assert m.char_offset == 0
        assert m.user_id is None
        assert m.badge_sent is False


class TestDiscordAdapterMetadata:
    @pytest.mark.unit
    def test_default_fields_are_none_or_falsy(self):
        m = DiscordAdapterMetadata()
        assert m.user_id is None
        assert m.guild_id is None
        assert m.channel_id is None
        assert m.thread_id is None
        assert m.all_sessions_thread_id is None
        assert m.output_message_id is None
        assert m.thread_topper_message_id is None
        assert m.status_message_id is None
        assert m.badge_sent is False
        assert m.char_offset == 0


class TestWhatsAppAdapterMetadata:
    @pytest.mark.unit
    def test_default_fields_are_none_or_falsy(self):
        m = WhatsAppAdapterMetadata()
        assert m.phone_number is None
        assert m.conversation_id is None
        assert m.output_message_id is None
        assert m.badge_sent is False
        assert m.char_offset == 0
        assert m.last_customer_message_at is None
        assert m.last_received_message_id is None
        assert m.closed is False


class TestUiAdapterMetadata:
    @pytest.mark.unit
    def test_get_telegram_initializes_on_first_call(self):
        ui = UiAdapterMetadata()
        result = ui.get_telegram()
        assert isinstance(result, TelegramAdapterMetadata)

    @pytest.mark.unit
    def test_get_telegram_returns_same_instance_on_repeated_calls(self):
        ui = UiAdapterMetadata()
        first = ui.get_telegram()
        second = ui.get_telegram()
        assert first is second

    @pytest.mark.unit
    def test_get_discord_initializes_on_first_call(self):
        ui = UiAdapterMetadata()
        result = ui.get_discord()
        assert isinstance(result, DiscordAdapterMetadata)

    @pytest.mark.unit
    def test_get_discord_returns_same_instance_on_repeated_calls(self):
        ui = UiAdapterMetadata()
        first = ui.get_discord()
        second = ui.get_discord()
        assert first is second

    @pytest.mark.unit
    def test_get_whatsapp_initializes_on_first_call(self):
        ui = UiAdapterMetadata()
        result = ui.get_whatsapp()
        assert isinstance(result, WhatsAppAdapterMetadata)

    @pytest.mark.unit
    def test_get_whatsapp_returns_same_instance_on_repeated_calls(self):
        ui = UiAdapterMetadata()
        first = ui.get_whatsapp()
        second = ui.get_whatsapp()
        assert first is second

    @pytest.mark.unit
    def test_pre_populated_telegram_is_returned_directly(self):
        tg = TelegramAdapterMetadata(topic_id=99)
        ui = UiAdapterMetadata(_telegram=tg)
        assert ui.get_telegram() is tg
        assert ui.get_telegram().topic_id == 99


class TestRedisTransportMetadata:
    @pytest.mark.unit
    def test_default_fields_are_none(self):
        m = RedisTransportMetadata()
        assert m.channel_id is None
        assert m.output_stream is None
        assert m.target_computer is None
        assert m.native_session_id is None
        assert m.project_path is None
        assert m.last_checkpoint_time is None
        assert m.title is None
        assert m.channel_metadata is None


class TestTransportAdapterMetadata:
    @pytest.mark.unit
    def test_get_redis_initializes_on_first_call(self):
        transport = TransportAdapterMetadata()
        result = transport.get_redis()
        assert isinstance(result, RedisTransportMetadata)

    @pytest.mark.unit
    def test_get_redis_returns_same_instance_on_repeated_calls(self):
        transport = TransportAdapterMetadata()
        first = transport.get_redis()
        second = transport.get_redis()
        assert first is second


class TestSessionAdapterMetadata:
    @pytest.mark.unit
    def test_empty_serializes_to_empty_json_object(self):
        meta = SessionAdapterMetadata()
        data = json.loads(meta.to_json())
        assert data == {}

    @pytest.mark.unit
    def test_telegram_shorthand_init_populates_ui(self):
        tg = TelegramAdapterMetadata(topic_id=42)
        meta = SessionAdapterMetadata(telegram=tg)
        assert meta.get_ui().get_telegram().topic_id == 42

    @pytest.mark.unit
    def test_get_ui_returns_ui_adapter_metadata(self):
        meta = SessionAdapterMetadata()
        assert isinstance(meta.get_ui(), UiAdapterMetadata)

    @pytest.mark.unit
    def test_get_transport_returns_transport_adapter_metadata(self):
        meta = SessionAdapterMetadata()
        assert isinstance(meta.get_transport(), TransportAdapterMetadata)

    @pytest.mark.unit
    def test_to_json_excludes_none_fields(self):
        tg = TelegramAdapterMetadata(topic_id=5, char_offset=0, output_suppressed=False, badge_sent=False)
        meta = SessionAdapterMetadata(telegram=tg)
        data = json.loads(meta.to_json())
        # None fields must not appear
        assert "output_message_id" not in data.get("telegram", {})
        assert "footer_message_id" not in data.get("telegram", {})

    @pytest.mark.unit
    def test_to_json_includes_set_fields(self):
        tg = TelegramAdapterMetadata(topic_id=7, char_offset=3)
        meta = SessionAdapterMetadata(telegram=tg)
        data = json.loads(meta.to_json())
        assert data["telegram"]["topic_id"] == 7
        assert data["telegram"]["char_offset"] == 3

    @pytest.mark.unit
    def test_from_json_roundtrip_telegram(self):
        tg = TelegramAdapterMetadata(topic_id=10, output_message_id="msg1", char_offset=5)
        original = SessionAdapterMetadata(telegram=tg)
        restored = SessionAdapterMetadata.from_json(original.to_json())
        restored_tg = restored.get_ui().get_telegram()
        assert restored_tg.topic_id == 10
        assert restored_tg.output_message_id == "msg1"
        assert restored_tg.char_offset == 5

    @pytest.mark.unit
    def test_from_json_topic_id_as_string_converted_to_int(self):
        raw = json.dumps({"telegram": {"topic_id": "123"}})
        meta = SessionAdapterMetadata.from_json(raw)
        assert meta.get_ui().get_telegram().topic_id == 123

    @pytest.mark.unit
    def test_from_json_roundtrip_discord(self):
        dc = DiscordAdapterMetadata(guild_id=100, channel_id=200, char_offset=2)
        original = SessionAdapterMetadata(discord=dc)
        restored = SessionAdapterMetadata.from_json(original.to_json())
        restored_dc = restored.get_ui().get_discord()
        assert restored_dc.guild_id == 100
        assert restored_dc.channel_id == 200
        assert restored_dc.char_offset == 2

    @pytest.mark.unit
    def test_from_json_roundtrip_redis(self):
        redis = RedisTransportMetadata(channel_id="ch1", target_computer="node1")
        original = SessionAdapterMetadata(redis=redis)
        restored = SessionAdapterMetadata.from_json(original.to_json())
        restored_redis = restored.get_transport().get_redis()
        assert restored_redis.channel_id == "ch1"
        assert restored_redis.target_computer == "node1"

    @pytest.mark.unit
    def test_from_json_redis_channel_metadata_dict_becomes_json_string(self):
        raw = json.dumps({"redis": {"channel_metadata": {"key": "val"}}})
        meta = SessionAdapterMetadata.from_json(raw)
        stored = meta.get_transport().get_redis().channel_metadata
        assert isinstance(stored, str)
        assert json.loads(stored) == {"key": "val"}

    @pytest.mark.unit
    def test_from_json_empty_object_produces_no_adapters(self):
        meta = SessionAdapterMetadata.from_json("{}")
        assert meta.get_ui()._telegram is None
        assert meta.get_ui()._discord is None
        assert meta.get_ui()._whatsapp is None
        assert meta.get_transport()._redis is None

    @pytest.mark.unit
    def test_from_json_threaded_footer_alias_accepted(self):
        raw = json.dumps({"telegram": {"threaded_footer_message_id": "ftr99"}})
        meta = SessionAdapterMetadata.from_json(raw)
        assert meta.get_ui().get_telegram().footer_message_id == "ftr99"
