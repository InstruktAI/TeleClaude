"""Leaf file helpers shared across next-machine modules."""

from __future__ import annotations

import hashlib
from pathlib import Path


def read_text_sync(path: Path) -> str:
    """Read text from a file in a typed sync wrapper."""
    return path.read_text(encoding="utf-8")


def write_text_sync(path: Path, content: str) -> None:
    """Write text to a file in a typed sync wrapper."""
    path.write_text(content, encoding="utf-8")


def file_sha256(path: Path) -> str:
    """Return sha256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()
