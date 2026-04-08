"""HVSC Songlengths.md5 database — maps SID file MD5 to play durations."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_DURATION_RE = re.compile(r"^(\d+):(\d{2})(?:\.(\d{1,3}))?$")


def _parse_duration(s: str) -> float:
    """Parse 'mm:ss' or 'mm:ss.SSS' to seconds."""
    m = _DURATION_RE.match(s)
    if not m:
        return 0.0
    minutes, seconds = int(m.group(1)), int(m.group(2))
    # Pad millis: '1' → 100ms, '12' → 120ms, '123' → 123ms
    millis_str = m.group(3) or "0"
    millis = int(millis_str.ljust(3, "0"))
    return minutes * 60.0 + seconds + millis / 1000.0


def load_songlengths(db_path: Path) -> dict[str, list[float]]:
    """Parse the HVSC Songlengths.md5 database into {md5: [duration_per_subtune]}.

    Returns an empty dict if the file is missing or unreadable.
    """
    result: dict[str, list[float]] = {}
    try:
        text = db_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("Songlengths database not found: %s", db_path)
        return result

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("["):
            continue
        eq = line.find("=")
        if eq < 0:
            continue
        md5_hex = line[:eq].strip().lower()
        durations_str = line[eq + 1 :].strip()
        if not md5_hex or not durations_str:
            continue
        durations = [_parse_duration(d) for d in durations_str.split()]
        if durations:
            result[md5_hex] = durations

    logger.info("Loaded %d entries from songlengths database", len(result))
    return result


def lookup_duration(db: dict[str, list[float]], sid_path: Path, subtune: int = 0) -> float | None:
    """Return the known duration in seconds for a SID file's subtune, or None."""
    try:
        data = sid_path.read_bytes()
    except OSError:
        return None
    md5_hex = hashlib.md5(data).hexdigest()  # noqa: S324
    durations = db.get(md5_hex)
    if durations is None:
        return None
    if subtune < 0 or subtune >= len(durations):
        return durations[0] if durations else None
    return durations[subtune]
