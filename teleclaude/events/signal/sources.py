"""Signal source configuration models and loaders."""

from __future__ import annotations

import asyncio
import csv
import io
from enum import Enum
from pathlib import Path
from xml.etree import ElementTree

from pydantic import BaseModel, model_validator


class SourceType(str, Enum):
    """Supported source declaration types for signal ingestion."""

    RSS = "rss"
    OPML = "opml"
    CSV = "csv"
    YOUTUBE = "youtube"
    TWITTER = "twitter"


class SourceConfig(BaseModel):
    """One signal source definition or file reference."""

    type: SourceType
    label: str = ""
    url: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> SourceConfig:
        """Validate that URL- and path-based source types provide the required field."""
        if self.type in (SourceType.RSS, SourceType.YOUTUBE, SourceType.TWITTER):
            if not self.url:
                raise ValueError(f"SourceConfig type={self.type} requires 'url'")
        if self.type in (SourceType.OPML, SourceType.CSV):
            if not self.path:
                raise ValueError(f"SourceConfig type={self.type} requires 'path'")
        return self


class SignalSourceConfig(BaseModel):
    """Root configuration for the signal source loader and pull loop."""

    sources: list[SourceConfig] = []
    pull_interval_seconds: int = 900
    max_items_per_pull: int = 50
    ai_concurrency: int = 5


def _parse_opml(xml_text: str, path_label: str) -> list[SourceConfig]:
    """Expand an OPML document into individual RSS source entries."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as e:
        raise ValueError(f"Invalid OPML XML in {path_label}: {e}") from e
    results: list[SourceConfig] = []
    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl")
        if xml_url:
            label = outline.get("text") or outline.get("title") or ""
            results.append(SourceConfig(type=SourceType.RSS, url=xml_url, label=label))
    return results


def _parse_csv(csv_text: str) -> list[SourceConfig]:
    """Expand a CSV source list into typed source entries."""
    results: list[SourceConfig] = []
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if not row or row[0].startswith("#"):
            continue
        label = row[0].strip() if len(row) > 0 else ""
        url = row[1].strip() if len(row) > 1 else ""
        type_str = row[2].strip() if len(row) > 2 else "rss"
        if not url:
            continue
        try:
            src_type = SourceType(type_str.lower())
        except ValueError:
            src_type = SourceType.RSS
        results.append(SourceConfig(type=src_type, url=url, label=label))
    return results


async def load_sources(config: SignalSourceConfig) -> list[SourceConfig]:
    """Expand any file-reference sources (OPML, CSV) into flat SourceConfig list."""
    result: list[SourceConfig] = []
    for source in config.sources:
        if source.type in (SourceType.OPML, SourceType.CSV) and source.path:
            resolved = Path(source.path).expanduser()
            if not resolved.exists():
                raise FileNotFoundError(f"Signal source file not found: {resolved}")
            text = await asyncio.to_thread(resolved.read_text, encoding="utf-8")
            if source.type == SourceType.OPML:
                result.extend(_parse_opml(text, str(resolved)))
            else:
                result.extend(_parse_csv(text))
        else:
            result.append(source)
    return result
