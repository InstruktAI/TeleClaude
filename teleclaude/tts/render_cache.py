"""Bounded-lifetime, owner-only cache for rendered Discord-room reply artifacts.

Keyed on (session_id, output_version, service, voice) so an unchanged reply is
never re-synthesized (SC-10): a cache hit returns the existing file without
calling any backend's render(). Each key owns one directory rather than a
fixed filename, since backends render to different extensions (mp3/wav/aiff).
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_CACHE_ROOT: Final = Path(tempfile.gettempdir()) / "teleclaude_tts" / "discord_render_cache"
_OWNER_ONLY_DIR_MODE: Final = 0o700
_ENTRY_LIFETIME_S: Final = 3600
_ARTIFACT_GLOB: Final = "reply.*"


@dataclass(frozen=True)
class RenderCacheKey:
    """Identity of one rendered artifact: the version this room has already heard."""

    session_id: str
    output_version: str
    service: str
    voice: str

    def slug(self) -> str:
        digest_input = f"{self.session_id}:{self.output_version}:{self.service}:{self.voice}"
        return hashlib.sha256(digest_input.encode()).hexdigest()[:32]


def _ensure_root() -> None:
    _CACHE_ROOT.mkdir(parents=True, mode=_OWNER_ONLY_DIR_MODE, exist_ok=True)


def lookup(key: RenderCacheKey) -> Path | None:
    """Return the cached rendered artifact for ``key`` if a live entry exists."""
    _ensure_root()
    entry_dir = _CACHE_ROOT / key.slug()
    if not entry_dir.is_dir():
        return None
    artifacts = sorted(entry_dir.glob(_ARTIFACT_GLOB))
    if not artifacts:
        return None
    artifact = artifacts[0]
    if not artifact.stat().st_size:
        return None
    if time.time() - artifact.stat().st_mtime >= _ENTRY_LIFETIME_S:
        return None
    return artifact


def dir_for(key: RenderCacheKey) -> Path:
    """Return the directory a fresh render for ``key`` should write into."""
    _ensure_root()
    entry_dir = _CACHE_ROOT / key.slug()
    entry_dir.mkdir(mode=_OWNER_ONLY_DIR_MODE, exist_ok=True)
    return entry_dir
