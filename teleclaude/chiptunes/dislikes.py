"""Chiptunes dislikes persistence — local JSON file, no daemon API."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.paths import CHIPTUNES_DISLIKES_PATH

logger = get_logger(__name__)

DISLIKES_PATH = CHIPTUNES_DISLIKES_PATH


def load_dislikes() -> list[dict[str, str]]:  # guard: loose-dict - dislikes entry
    """Load dislikes from disk. Returns empty list if file is missing or corrupt."""
    try:
        data = json.loads(DISLIKES_PATH.read_text())
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        logger.warning("Chiptunes dislikes file is corrupted: %s", DISLIKES_PATH, exc_info=True)
        return []

    if not isinstance(data, list):
        logger.warning("Chiptunes dislikes file is malformed (expected list): %s", DISLIKES_PATH)
        return []

    return data


def save_dislike(track_name: str, sid_path: str) -> None:
    """Append a new dislike entry, deduplicating by sid_path."""
    dislikes = load_dislikes()
    if any(d.get("sid_path") == sid_path for d in dislikes):
        return

    dislikes.append(
        {
            "track_name": track_name,
            "sid_path": sid_path,
            "saved_at": datetime.now(UTC).isoformat(),
        }
    )

    DISLIKES_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISLIKES_PATH.write_text(json.dumps(dislikes, indent=2))


def remove_dislike(sid_path: str) -> bool:
    """Remove a dislike entry by sid_path. Returns True when an entry was removed."""
    dislikes = load_dislikes()
    kept = [d for d in dislikes if d.get("sid_path") != sid_path]
    if len(kept) == len(dislikes):
        return False

    DISLIKES_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISLIKES_PATH.write_text(json.dumps(kept, indent=2))
    return True


def is_disliked(sid_path: str) -> bool:
    """Return True if sid_path exists in the dislikes list."""
    return any(d.get("sid_path") == sid_path for d in load_dislikes())


def disliked_paths() -> set[str]:
    """Return set of all disliked sid_paths for filtering during track discovery."""
    return {d["sid_path"] for d in load_dislikes() if "sid_path" in d}
