"""Unit tests for signal HTTP fetch utilities."""

from __future__ import annotations

import textwrap
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude_events.signal.fetch import fetch_full_content, parse_rss_feed


RSS2_FIXTURE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Channel</title>
        <item>
          <title>First Article</title>
          <link>https://example.com/first</link>
          <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
          <description>First article description.</description>
        </item>
        <item>
          <title>Second Article</title>
          <link>https://example.com/second</link>
          <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
          <description>Second article description.</description>
        </item>
      </channel>
    </rss>
""")

ATOM_FIXTURE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Feed</title>
      <entry>
        <title>Atom Entry One</title>
        <link href="https://atom.example.com/one"/>
        <published>2024-01-01T00:00:00Z</published>
        <summary>Summary of entry one.</summary>
      </entry>
      <entry>
        <title>Atom Entry Two</title>
        <link href="https://atom.example.com/two"/>
        <updated>2024-01-02T00:00:00Z</updated>
        <content>Content of entry two.</content>
      </entry>
    </feed>
""")


def test_parse_rss_feed_rss2() -> None:
    items = parse_rss_feed(RSS2_FIXTURE)
    assert len(items) == 2
    assert items[0]["title"] == "First Article"
    assert items[0]["url"] == "https://example.com/first"
    assert items[0]["published"] == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert items[0]["description"] == "First article description."
    assert items[1]["title"] == "Second Article"


def test_parse_rss_feed_atom() -> None:
    items = parse_rss_feed(ATOM_FIXTURE)
    assert len(items) == 2
    assert items[0]["title"] == "Atom Entry One"
    assert items[0]["url"] == "https://atom.example.com/one"
    assert items[0]["published"] == "2024-01-01T00:00:00Z"
    assert items[0]["description"] == "Summary of entry one."
    assert items[1]["url"] == "https://atom.example.com/two"


def test_parse_rss_feed_invalid_xml_returns_empty() -> None:
    result = parse_rss_feed("<not valid xml")
    assert result == []


def test_parse_rss_feed_empty_xml_returns_empty() -> None:
    result = parse_rss_feed("<rss><channel></channel></rss>")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_full_content_strips_html() -> None:
    html = "<html><head><title>Page</title></head><body><h1>Hello</h1><p>World text.</p></body></html>"
    from teleclaude_events.signal.fetch import FetchResult

    mock_result = FetchResult(
        url="https://example.com/page", status=200, content_type="text/html", body=html, error=None
    )
    with patch("teleclaude_events.signal.fetch.fetch_url", new=AsyncMock(return_value=mock_result)):
        result = await fetch_full_content("https://example.com/page")

    assert result is not None
    assert "Hello" in result
    assert "World text." in result
    assert "<" not in result  # no HTML tags


@pytest.mark.asyncio
async def test_fetch_full_content_truncates_to_max_chars() -> None:
    long_text = "A" * 20000
    html = f"<body><p>{long_text}</p></body>"
    from teleclaude_events.signal.fetch import FetchResult

    mock_result = FetchResult(
        url="https://example.com/page", status=200, content_type="text/html", body=html, error=None
    )
    with patch("teleclaude_events.signal.fetch.fetch_url", new=AsyncMock(return_value=mock_result)):
        result = await fetch_full_content("https://example.com/page", max_chars=100)

    assert result is not None
    assert len(result) <= 100


@pytest.mark.asyncio
async def test_fetch_full_content_returns_none_on_error() -> None:
    from teleclaude_events.signal.fetch import FetchResult

    mock_result = FetchResult(
        url="https://example.com/missing", status=404, content_type="text/html", body=None, error="HTTP 404"
    )
    with patch("teleclaude_events.signal.fetch.fetch_url", new=AsyncMock(return_value=mock_result)):
        result = await fetch_full_content("https://example.com/missing")

    assert result is None
