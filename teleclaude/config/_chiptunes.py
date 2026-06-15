"""Chiptunes configuration parsing."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.config._coerce import as_bool


@dataclass
class ChiptunesConfig:
    enabled: bool = False
    music_dir: str | None = None
    volume: float = 1.0


def parse_chiptunes_config(raw: dict[str, object] | None) -> ChiptunesConfig:  # guard: loose-dict
    data = raw or {}
    return ChiptunesConfig(
        enabled=as_bool(data.get("enabled", False)),
        music_dir=str(data["music_dir"]) if data.get("music_dir") else None,
        volume=float(data.get("volume", 0.5)),  # type: ignore[arg-type]
    )
