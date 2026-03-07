"""Chiptunes favorites persistence — local JSON file, no daemon API."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from instrukt_ai_logging import get_logger

from teleclaude.paths import CHIPTUNES_FAVORITES_PATH

logger = get_logger(__name__)

FAVORITES_PATH = CHIPTUNES_FAVORITES_PATH


def load_favorites() -> list[dict[str, str]]:  # guard: loose-dict - favorites entry
    """Load favorites from disk. Returns empty list if file is missing or corrupt."""
    try:
        data = json.loads(FAVORITES_PATH.read_text())
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        logger.warning("Chiptunes favorites file is corrupted: %s", FAVORITES_PATH, exc_info=True)
        return []

    if not isinstance(data, list):
        logger.warning("Chiptunes favorites file is malformed (expected list): %s", FAVORITES_PATH)
        return []

    return data


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


def remove_favorite(sid_path: str) -> bool:
    """Remove a favorite entry by sid_path. Returns True when an entry was removed."""
    favs = load_favorites()
    kept = [fav for fav in favs if fav.get("sid_path") != sid_path]
    if len(kept) == len(favs):
        return False

    FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_PATH.write_text(json.dumps(kept, indent=2))
    return True


def is_favorited(sid_path: str) -> bool:
    """Return True if sid_path exists in the favorites list."""
    return any(f.get("sid_path") == sid_path for f in load_favorites())
