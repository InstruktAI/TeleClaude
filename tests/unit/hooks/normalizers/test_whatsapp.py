"""Characterization tests for teleclaude.hooks.normalizers.whatsapp."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.hooks.normalizers.whatsapp import normalize_whatsapp_webhook


class TestNormalizeWhatsappWebhook:
    @pytest.mark.unit
    def test_returns_an_empty_list_when_entry_is_missing(self) -> None:
        assert normalize_whatsapp_webhook({}, {}) == []

    @pytest.mark.unit
    def test_text_messages_are_normalized_into_message_text_events(self) -> None:
        events = normalize_whatsapp_webhook(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "wamid-1",
                                            "from": "+1 (555) 123-4567",
                                            "timestamp": "1700000000",
                                            "type": "text",
                                            "text": {"body": "hello"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            },
            {},
        )

        assert len(events) == 1
        assert events[0].type == "message.text"
        assert events[0].timestamp == "2023-11-14T22:13:20+00:00"
        assert events[0].properties == {
            "phone_number": "15551234567",
            "message_id": "wamid-1",
            "text": "hello",
        }

    @pytest.mark.unit
    def test_audio_messages_with_non_ogg_mime_type_normalize_as_message_audio(self) -> None:
        events = normalize_whatsapp_webhook(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "wamid-2",
                                            "from": "555",
                                            "timestamp": "bad",
                                            "type": "audio",
                                            "audio": {"id": "media-1", "mime_type": "audio/mpeg"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            },
            {},
        )

        assert len(events) == 1
        assert events[0].type == "message.audio"
        assert events[0].properties == {
            "phone_number": "555",
            "message_id": "wamid-2",
            "media_id": "media-1",
            "mime_type": "audio/mpeg",
        }
        assert datetime.fromisoformat(events[0].timestamp).tzinfo == UTC

    @pytest.mark.unit
    def test_voice_messages_prefer_message_voice_even_when_sent_as_audio(self) -> None:
        events = normalize_whatsapp_webhook(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": "wamid-3",
                                            "from": "555",
                                            "timestamp": "1700000000",
                                            "type": "audio",
                                            "audio": {"id": "media-2", "mime_type": "audio/ogg"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            },
            {},
        )

        assert events[0].type == "message.voice"
