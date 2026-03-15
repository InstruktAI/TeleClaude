"""Characterization tests for teleclaude.events.signal.sources."""

from __future__ import annotations

import tempfile

import pytest

from teleclaude.events.signal.sources import (
    SignalSourceConfig,
    SourceConfig,
    SourceType,
    _parse_csv,
    _parse_opml,
    load_sources,
)


def test_source_type_enum_values() -> None:
    assert SourceType.RSS.value == "rss"
    assert SourceType.OPML.value == "opml"
    assert SourceType.CSV.value == "csv"
    assert SourceType.YOUTUBE.value == "youtube"
    assert SourceType.TWITTER.value == "twitter"


def test_source_config_rss_requires_url() -> None:
    with pytest.raises(ValueError, match="requires 'url'"):
        SourceConfig(type=SourceType.RSS, url=None)


def test_source_config_opml_requires_path() -> None:
    with pytest.raises(ValueError, match="requires 'path'"):
        SourceConfig(type=SourceType.OPML, path=None)


def test_source_config_csv_requires_path() -> None:
    with pytest.raises(ValueError, match="requires 'path'"):
        SourceConfig(type=SourceType.CSV, path=None)


def test_source_config_rss_valid() -> None:
    config = SourceConfig(type=SourceType.RSS, url="https://example.com/feed.rss", label="Test")
    assert config.url == "https://example.com/feed.rss"
    assert config.label == "Test"


def test_signal_source_config_defaults() -> None:
    config = SignalSourceConfig()
    assert config.sources == []
    assert config.pull_interval_seconds == 900
    assert config.max_items_per_pull == 50
    assert config.ai_concurrency == 5


def test_parse_opml_extracts_rss_urls() -> None:
    opml = """<?xml version="1.0"?>
    <opml version="2.0">
      <body>
        <outline text="Feed One" xmlUrl="https://feed1.example.com/rss"/>
        <outline text="Feed Two" xmlUrl="https://feed2.example.com/rss"/>
      </body>
    </opml>"""
    results = _parse_opml(opml, "test.opml")
    assert len(results) == 2
    urls = {r.url for r in results}
    assert "https://feed1.example.com/rss" in urls
    assert "https://feed2.example.com/rss" in urls
    for r in results:
        assert r.type == SourceType.RSS


def test_parse_opml_skips_outlines_without_xml_url() -> None:
    opml = """<?xml version="1.0"?>
    <opml version="2.0">
      <body>
        <outline text="Category"/>
        <outline text="Feed" xmlUrl="https://feed.example.com/rss"/>
      </body>
    </opml>"""
    results = _parse_opml(opml, "test.opml")
    assert len(results) == 1


def test_parse_opml_raises_on_invalid_xml() -> None:
    with pytest.raises(ValueError, match="Invalid OPML"):
        _parse_opml("not xml {{{", "bad.opml")


def test_parse_csv_extracts_sources() -> None:
    csv_text = "Feed One,https://feed1.example.com/rss,rss\nFeed Two,https://feed2.example.com/rss,rss\n"
    results = _parse_csv(csv_text)
    assert len(results) == 2
    assert results[0].url == "https://feed1.example.com/rss"
    assert results[0].label == "Feed One"
    assert results[0].type == SourceType.RSS


def test_parse_csv_skips_comment_lines() -> None:
    csv_text = "# comment\nFeed,https://feed.example.com/rss,rss\n"
    results = _parse_csv(csv_text)
    assert len(results) == 1


def test_parse_csv_skips_rows_without_url() -> None:
    csv_text = "NoUrl,,rss\nFeed,https://feed.example.com/rss,rss\n"
    results = _parse_csv(csv_text)
    assert len(results) == 1


def test_parse_csv_defaults_to_rss_for_unknown_type() -> None:
    csv_text = "Feed,https://feed.example.com/rss,unknown_type\n"
    results = _parse_csv(csv_text)
    assert len(results) == 1
    assert results[0].type == SourceType.RSS


async def test_load_sources_passthrough_for_rss_sources() -> None:
    config = SignalSourceConfig(
        sources=[
            SourceConfig(type=SourceType.RSS, url="https://example.com/rss", label="Test"),
        ]
    )
    result = await load_sources(config)
    assert len(result) == 1
    assert result[0].url == "https://example.com/rss"


async def test_load_sources_expands_opml_file() -> None:
    opml = """<?xml version="1.0"?>
    <opml version="2.0">
      <body>
        <outline text="Feed" xmlUrl="https://feed.example.com/rss"/>
      </body>
    </opml>"""
    with tempfile.NamedTemporaryFile(suffix=".opml", mode="w", delete=False) as f:
        f.write(opml)
        path = f.name

    config = SignalSourceConfig(sources=[SourceConfig(type=SourceType.OPML, path=path)])
    result = await load_sources(config)
    assert len(result) == 1
    assert result[0].url == "https://feed.example.com/rss"


async def test_load_sources_raises_for_missing_file() -> None:
    config = SignalSourceConfig(sources=[SourceConfig(type=SourceType.OPML, path="/nonexistent/path.opml")])
    with pytest.raises(FileNotFoundError):
        await load_sources(config)
