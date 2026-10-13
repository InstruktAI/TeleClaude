"""Chiptunes favorites persistence — a local JSON file the daemon's chiptunes routes own writes to."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.file_transaction import file_transaction
from teleclaude.paths import CHIPTUNES_FAVORITES_PATH

logger = get_logger(__name__)

FAVORITES_PATH = CHIPTUNES_FAVORITES_PATH


def _parse_favorites(raw: str) -> list[dict[str, str]]:  # guard: loose-dict - favorites entry
    """Parse favorites content. Returns empty list if it is empty or corrupt."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Chiptunes favorites file is corrupted: %s", FAVORITES_PATH, exc_info=True)
        return []

    if not isinstance(data, list):
        logger.warning("Chiptunes favorites file is malformed (expected list): %s", FAVORITES_PATH)
        return []

    return data


def load_favorites() -> list[dict[str, str]]:  # guard: loose-dict - favorites entry
    """Load favorites from disk. Returns empty list if file is missing or corrupt."""
    try:
        raw = FAVORITES_PATH.read_text()
    except FileNotFoundError:
        return []
    return _parse_favorites(raw)


def save_favorite(track_name: str, sid_path: str) -> None:
    """Append a new favorite entry, deduplicating by sid_path."""
    with file_transaction(FAVORITES_PATH) as transaction:
        favs = _parse_favorites(transaction.read_text())
        if any(f.get("sid_path") == sid_path for f in favs):
            return

        favs.append(
            {
                "track_name": track_name,
                "sid_path": sid_path,
                "saved_at": datetime.now(UTC).isoformat(),
            }
        )
        transaction.replace_text(json.dumps(favs, indent=2))


def remove_favorite(sid_path: str) -> bool:
    """Remove a favorite entry by sid_path. Returns True when an entry was removed."""
    with file_transaction(FAVORITES_PATH) as transaction:
        favs = _parse_favorites(transaction.read_text())
        kept = [fav for fav in favs if fav.get("sid_path") != sid_path]
        if len(kept) == len(favs):
            return False

        transaction.replace_text(json.dumps(kept, indent=2))
        return True


def is_favorited(sid_path: str) -> bool:
    """Return True if sid_path exists in the favorites list."""
    return any(f.get("sid_path") == sid_path for f in load_favorites())
