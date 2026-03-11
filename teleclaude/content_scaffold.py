"""Scaffold content inbox entries for the publications pipeline."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import yaml

from teleclaude.slug import ensure_unique_slug, normalize_slug


def _derive_slug(text: str) -> str:
    """Derive a slug from the first few meaningful words of text."""
    lowered = text.lower()
    words_only = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    words = [w for w in words_only.split() if len(w) > 1][:5]
    slug = normalize_slug("-".join(words))
    return slug or "dump"


def _resolve_author() -> str:
    """Resolve the current terminal auth identity, or 'unknown'."""
    try:
        from teleclaude.cli.session_auth import read_current_session_email

        email = read_current_session_email()
        return email or "unknown"
    except Exception:
        return "unknown"


class _MetaPayload(TypedDict):
    author: str
    tags: list[str]
    created_at: str


def create_content_inbox_entry(
    project_root: Path,
    text: str,
    *,
    slug: str | None = None,
    tags: list[str] | None = None,
    author: str | None = None,
) -> Path:
    """Create a publications inbox entry (files only).

    Returns the created directory path. Notification emission is the
    caller's responsibility.
    """
    resolved_author = author if author is not None else _resolve_author()
    resolved_tags = tags or []

    now = datetime.now(UTC)
    date_prefix = now.strftime("%Y%m%d")
    base_slug = slug if slug else _derive_slug(text)
    folder_name = f"{date_prefix}-{base_slug}"

    inbox_dir = project_root / "publications" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    folder_name = ensure_unique_slug(inbox_dir, folder_name)
    entry_dir = inbox_dir / folder_name

    entry_dir.mkdir(parents=True)

    (entry_dir / "content.md").write_text(text, encoding="utf-8")

    meta: _MetaPayload = {
        "author": resolved_author,
        "tags": resolved_tags,
        "created_at": now.isoformat(),
    }
    (entry_dir / "meta.yaml").write_text(yaml.dump(meta, default_flow_style=False), encoding="utf-8")

    return entry_dir
