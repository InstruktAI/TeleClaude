"""HTTP fetch utilities for signal ingest."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from xml.etree import ElementTree

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    body: str | None
    error: str | None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_tags = {"script", "style", "noscript", "head"}
        self._current_skip: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._skip_tags:
            self._current_skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip_tags and self._current_skip > 0:
            self._current_skip -= 1

    def handle_data(self, data: str) -> None:
        if self._current_skip == 0:
            stripped = data.strip()
            if stripped:
                self._chunks.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._chunks)


async def fetch_url(url: str, timeout: int = 10) -> FetchResult:
    """Fetch a URL and return a FetchResult."""
    try:
        import aiohttp
    except ImportError:
        return FetchResult(url=url, status=0, content_type="", body=None, error="aiohttp not available")

    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with session.get(url) as resp:
                content_type = resp.content_type or ""
                if resp.status == 200:
                    body = await resp.text()
                    return FetchResult(url=url, status=resp.status, content_type=content_type, body=body, error=None)
                return FetchResult(
                    url=url,
                    status=resp.status,
                    content_type=content_type,
                    body=None,
                    error=f"HTTP {resp.status}",
                )
    except Exception as e:
        return FetchResult(url=url, status=0, content_type="", body=None, error=str(e))


async def fetch_full_content(url: str, max_chars: int = 8000) -> str | None:
    """Fetch HTML page and return stripped plain-text content, truncated to max_chars."""
    result = await fetch_url(url)
    if result.error or result.body is None:
        return None
    extractor = _TextExtractor()
    try:
        extractor.feed(result.body)
        text = extractor.get_text()
    except Exception as e:
        logger.warning("HTML parse fallback for %s: %s", url, e)
        text = re.sub(r"<[^>]+>", " ", result.body)
        text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars] if len(text) > max_chars else text or None


def _parse_atom_feed(root: ElementTree.Element) -> list[dict]:
    """Parse Atom feed entries."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        published_el = entry.find("atom:published", ns)
        if published_el is None:
            published_el = entry.find("atom:updated", ns)
        summary_el = entry.find("atom:summary", ns)
        if summary_el is None:
            summary_el = entry.find("atom:content", ns)

        title = title_el.text or "" if title_el is not None else ""
        url = link_el.get("href", "") if link_el is not None else ""
        published = published_el.text or "" if published_el is not None else ""
        description = summary_el.text or "" if summary_el is not None else ""

        if url:
            items.append({"title": title, "url": url, "published": published, "description": description})
    return items


def _parse_rss2_feed(root: ElementTree.Element) -> list[dict]:
    """Parse RSS 2.0 channel items."""
    items: list[dict] = []
    channel = root.find("channel")
    if channel is None:
        channel = root
    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        desc_el = item.find("description")

        title = title_el.text or "" if title_el is not None else ""
        url = link_el.text or "" if link_el is not None else ""
        published = pub_el.text or "" if pub_el is not None else ""
        description = desc_el.text or "" if desc_el is not None else ""

        if url:
            items.append({"title": title, "url": url, "published": published, "description": description})
    return items


def parse_rss_feed(xml: str) -> list[dict]:
    """Parse RSS 2.0 or Atom feed XML and return a list of item dicts.

    Each dict has keys: title, url, published, description.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        logger.warning("RSS feed XML parse error (content_length=%d): %s", len(xml), e)
        return []

    tag = root.tag.lower()
    if "feed" in tag or root.tag == "{http://www.w3.org/2005/Atom}feed":
        return _parse_atom_feed(root)
    return _parse_rss2_feed(root)
