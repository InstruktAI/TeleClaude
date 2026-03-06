"""Unit tests for signal source config and loaders."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from teleclaude_events.signal.sources import (
    SignalSourceConfig,
    SourceConfig,
    SourceType,
    _parse_csv,
    _parse_opml,
    load_sources,
)


@pytest.mark.asyncio
async def test_inline_sources_loaded_as_is() -> None:
    config = SignalSourceConfig(
        sources=[
            SourceConfig(type=SourceType.RSS, url="https://example.com/feed.xml", label="example"),
            SourceConfig(type=SourceType.RSS, url="https://other.com/rss", label="other"),
        ]
    )
    result = await load_sources(config)
    assert len(result) == 2
    assert result[0].url == "https://example.com/feed.xml"
    assert result[1].label == "other"


def test_parse_opml_extracts_rss_sources() -> None:
    opml = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <opml version="1.0">
          <head><title>My Feeds</title></head>
          <body>
            <outline text="Tech News" xmlUrl="https://tech.example.com/rss"/>
            <outline text="Science" xmlUrl="https://science.example.com/atom.xml"/>
            <outline text="No URL" title="no-url-outline"/>
          </body>
        </opml>
    """)
    result = _parse_opml(opml, "test.opml")
    assert len(result) == 2
    assert result[0].type == SourceType.RSS
    assert result[0].url == "https://tech.example.com/rss"
    assert result[0].label == "Tech News"
    assert result[1].url == "https://science.example.com/atom.xml"
    assert result[1].label == "Science"


def test_parse_opml_invalid_xml_raises() -> None:
    with pytest.raises(ValueError, match="Invalid OPML XML"):
        _parse_opml("<not valid xml", "bad.opml")


def test_parse_csv_extracts_sources() -> None:
    csv_text = textwrap.dedent("""\
        # comment line
        Tech Blog,https://tech.example.com/rss,rss
        Science News,https://science.example.com/feed,rss
        ,https://empty-label.com/rss,rss
    """)
    result = _parse_csv(csv_text)
    assert len(result) == 3
    assert result[0].label == "Tech Blog"
    assert result[0].url == "https://tech.example.com/rss"
    assert result[0].type == SourceType.RSS
    assert result[1].label == "Science News"
    assert result[2].label == ""  # empty label row


def test_parse_csv_unknown_type_defaults_to_rss() -> None:
    csv_text = "Feed,https://example.com/rss,unknown_type\n"
    result = _parse_csv(csv_text)
    assert len(result) == 1
    assert result[0].type == SourceType.RSS


@pytest.mark.asyncio
async def test_load_sources_opml_file(tmp_path: Path) -> None:
    opml_content = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <opml version="1.0">
          <body>
            <outline text="Feed A" xmlUrl="https://a.example.com/rss"/>
          </body>
        </opml>
    """)
    opml_file = tmp_path / "feeds.opml"
    opml_file.write_text(opml_content, encoding="utf-8")

    config = SignalSourceConfig(
        sources=[SourceConfig(type=SourceType.OPML, path=str(opml_file))]
    )
    result = await load_sources(config)
    assert len(result) == 1
    assert result[0].url == "https://a.example.com/rss"


@pytest.mark.asyncio
async def test_load_sources_csv_file(tmp_path: Path) -> None:
    csv_content = "My Feed,https://example.com/rss,rss\n"
    csv_file = tmp_path / "sources.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    config = SignalSourceConfig(
        sources=[SourceConfig(type=SourceType.CSV, path=str(csv_file))]
    )
    result = await load_sources(config)
    assert len(result) == 1
    assert result[0].url == "https://example.com/rss"


@pytest.mark.asyncio
async def test_load_sources_missing_file_raises() -> None:
    config = SignalSourceConfig(
        sources=[SourceConfig(type=SourceType.OPML, path="/nonexistent/path/feeds.opml")]
    )
    with pytest.raises(FileNotFoundError, match="Signal source file not found"):
        await load_sources(config)


def test_source_config_rss_requires_url() -> None:
    with pytest.raises(Exception):
        SourceConfig(type=SourceType.RSS)  # no url


def test_source_config_opml_requires_path() -> None:
    with pytest.raises(Exception):
        SourceConfig(type=SourceType.OPML)  # no path
