"""Characterization tests for teleclaude.events.signal.fetch."""

from __future__ import annotations

from teleclaude.events.signal.fetch import FetchResult, _TextExtractor, parse_rss_feed


def test_fetch_result_fields_accessible() -> None:
    result = FetchResult(url="http://example.com", status=200, content_type="text/html", body="hello", error=None)
    assert result.url == "http://example.com"
    assert result.status == 200
    assert result.content_type == "text/html"
    assert result.body == "hello"
    assert result.error is None


def test_text_extractor_strips_script_and_style() -> None:
    extractor = _TextExtractor()
    extractor.feed("<html><script>alert(1)</script><p>hello world</p></html>")
    assert "alert" not in extractor.get_text()
    assert "hello world" in extractor.get_text()


def test_text_extractor_strips_style_content() -> None:
    extractor = _TextExtractor()
    extractor.feed("<style>.a { color: red }</style><p>visible</p>")
    assert "color" not in extractor.get_text()
    assert "visible" in extractor.get_text()


def test_text_extractor_skips_head() -> None:
    extractor = _TextExtractor()
    extractor.feed("<head><title>ignore</title></head><body>body text</body>")
    text = extractor.get_text()
    assert "ignore" not in text
    assert "body text" in text


def test_text_extractor_empty_input_returns_empty_string() -> None:
    extractor = _TextExtractor()
    extractor.feed("")
    assert extractor.get_text() == ""


def test_parse_rss_feed_returns_empty_for_invalid_xml() -> None:
    result = parse_rss_feed("not xml at all {{")
    assert result == []


def test_parse_rss_feed_parses_rss2_items() -> None:
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Test Article</title>
          <link>https://example.com/article</link>
          <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
          <description>Summary text</description>
        </item>
      </channel>
    </rss>"""
    items = parse_rss_feed(xml)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/article"
    assert items[0]["title"] == "Test Article"


def test_parse_rss_feed_parses_atom_feed() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom Article</title>
        <link href="https://example.com/atom-article"/>
        <published>2024-01-01T00:00:00Z</published>
        <summary>Atom summary</summary>
      </entry>
    </feed>"""
    items = parse_rss_feed(xml)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/atom-article"
    assert items[0]["title"] == "Atom Article"


def test_parse_rss_feed_skips_items_without_url() -> None:
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>No URL item</title>
          <description>no link here</description>
        </item>
      </channel>
    </rss>"""
    items = parse_rss_feed(xml)
    assert items == []


def test_parse_rss_feed_returns_all_four_fields() -> None:
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Article</title>
          <link>https://example.com/item</link>
          <pubDate>Mon, 01 Jan 2024</pubDate>
          <description>Description here</description>
        </item>
      </channel>
    </rss>"""
    items = parse_rss_feed(xml)
    assert len(items) == 1
    item = items[0]
    assert "title" in item
    assert "url" in item
    assert "published" in item
    assert "description" in item
