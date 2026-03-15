"""Characterization tests for teleclaude.helpers.youtube_helper._parsers."""

from __future__ import annotations

import json

import pytest

from teleclaude.helpers.youtube_helper import _parsers
from teleclaude.helpers.youtube_helper._models import SubscriptionChannel

pytestmark = pytest.mark.unit


class _FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def get(self, url: str, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append((url, headers))
        return self.response


class TestParseHistoryEntries:
    def test_collects_lockup_and_video_renderer_entries(self) -> None:
        data = {
            "contents": {
                "twoColumnBrowseResultsRenderer": {
                    "tabs": [
                        {
                            "tabRenderer": {
                                "content": {
                                    "sectionListRenderer": {
                                        "contents": [
                                            {
                                                "itemSectionRenderer": {
                                                    "contents": [
                                                        {
                                                            "lockupViewModel": {
                                                                "contentId": "lockup-id",
                                                                "metadata": {
                                                                    "lockupMetadataViewModel": {
                                                                        "title": {"content": "Lockup title"},
                                                                        "metadata": {
                                                                            "contentMetadataViewModel": {
                                                                                "metadataRows": [
                                                                                    {
                                                                                        "metadataParts": [
                                                                                            {
                                                                                                "text": {
                                                                                                    "content": "Channel A"
                                                                                                }
                                                                                            },
                                                                                            {
                                                                                                "text": {
                                                                                                    "content": "1K views"
                                                                                                }
                                                                                            },
                                                                                        ]
                                                                                    },
                                                                                    {
                                                                                        "metadataParts": [
                                                                                            {
                                                                                                "text": {
                                                                                                    "content": "3 days ago"
                                                                                                }
                                                                                            }
                                                                                        ]
                                                                                    },
                                                                                ]
                                                                            }
                                                                        },
                                                                    }
                                                                },
                                                                "contentImage": {
                                                                    "thumbnailViewModel": {
                                                                        "overlays": [
                                                                            {
                                                                                "thumbnailBottomOverlayViewModel": {
                                                                                    "badges": [
                                                                                        {
                                                                                            "thumbnailBadgeViewModel": {
                                                                                                "text": "12:34"
                                                                                            }
                                                                                        }
                                                                                    ]
                                                                                }
                                                                            }
                                                                        ]
                                                                    }
                                                                },
                                                            }
                                                        },
                                                        {
                                                            "videoRenderer": {
                                                                "videoId": "video-id",
                                                                "title": {"runs": [{"text": "Renderer title"}]},
                                                                "longBylineText": {"runs": [{"text": "Channel B"}]},
                                                                "lengthText": {"simpleText": "5:00"},
                                                                "viewCountText": {"simpleText": "2K views"},
                                                                "publishedTimeText": {"simpleText": "1 hour ago"},
                                                                "navigationEndpoint": {
                                                                    "commandMetadata": {
                                                                        "webCommandMetadata": {
                                                                            "url": "/watch?v=video-id"
                                                                        }
                                                                    }
                                                                },
                                                            }
                                                        },
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }

        entries = _parsers._parse_history_entries(data)

        assert [entry["id"] for entry in entries] == ["lockup-id", "video-id"]
        assert entries[0]["publish_time"] == "3 days ago"
        assert entries[1]["channel"] == "Channel B"


class TestRichGridContinuation:
    def test_returns_first_continuation_token(self) -> None:
        contents = [
            {"richItemRenderer": {"content": {}}},
            {"continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": "next-token"}}}},
        ]

        assert _parsers._extract_richgrid_continuation(contents) == "next-token"


class TestFindAboutDescription:
    def test_recurses_through_nested_lists_and_dicts(self) -> None:
        payload = {
            "outer": [
                {},
                {
                    "inner": {
                        "descriptionPreviewViewModel": {"description": {"content": "About body"}},
                    }
                },
            ]
        }

        assert _parsers._find_about_description(payload) == "About body"


class TestFetchChannelAboutDescription:
    @pytest.mark.asyncio
    async def test_uses_handle_about_url_and_extracts_description(self) -> None:
        html = (
            "var ytInitialData = "
            + json.dumps({"data": {"descriptionPreviewViewModel": {"description": {"content": "Channel description"}}}})
            + ";"
        )
        session = _FakeSession(_FakeResponse(200, html))
        channel = SubscriptionChannel(id="channel-id", title="Channel", handle="@creator")

        description = await _parsers._fetch_channel_about_description(session, channel)

        assert description == "Channel description"
        assert session.calls[0][0] == "https://www.youtube.com/@creator/about?hl=en"
