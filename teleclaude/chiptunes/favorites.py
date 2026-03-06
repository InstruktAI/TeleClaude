"""Chiptunes favorites persistence — local JSON file, no daemon API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FAVORITES_PATH = Path("~/.teleclaude/chiptunes-favorites.json").expanduser()


def load_favorites() -> list[dict[str, str]]:  # guard: loose-dict - favorites entry
    """Load favorites from disk. Returns empty list if file is missing or malformed."""
    try:
        return json.loads(FAVORITES_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_favorite(track_name: str, sid_path: str) -> None:
    """Append a new favorite entry, deduplicating by sid_path."""
    favs = load_favorites()
    if any(f.get("sid_path") == sid_path for f in favs):
        return

    favs.append(
        {
            "track_name": track_name,
            "sid_path": sid_path,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_PATH.write_text(json.dumps(favs, indent=2))


def is_favorited(sid_path: str) -> bool:
    """Return True if sid_path exists in the favorites list."""
    return any(f.get("sid_path") == sid_path for f in load_favorites())
