"""Third-party doc index: model and loader.

Third-party docs are a parallel track to the taxonomy snippets — a simpler
schema with no taxonomy ``type`` field. The selection engine composes these
entries beside taxonomy snippets but loads them through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ThirdPartyMeta:
    """Third-party doc entry - no type field (not part of taxonomy)."""

    snippet_id: str
    description: str
    scope: str
    path: Path


def load_third_party_index(index_path: Path) -> list[ThirdPartyMeta]:
    """Load third-party index.yaml (simpler schema: no type field)."""
    if not index_path.exists():
        return []

    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("third_party_index_load_failed", path=str(index_path), error=str(exc))
        return []

    if not isinstance(payload, dict):
        return []

    snippets_root = payload.get("snippets_root")
    snippets = payload.get("snippets")
    if not isinstance(snippets_root, str) or not isinstance(snippets, list):
        return []

    root_path = Path(snippets_root).expanduser().resolve()
    entries: list[ThirdPartyMeta] = []
    for item in snippets:
        if not isinstance(item, dict):
            continue
        snippet_id = item.get("id")
        description = item.get("description")
        scope = item.get("scope")
        raw_path = item.get("path")
        if (
            not isinstance(snippet_id, str)
            or not isinstance(description, str)
            or not isinstance(scope, str)
            or not isinstance(raw_path, str)
        ):
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (root_path / path).resolve()
        entries.append(
            ThirdPartyMeta(
                snippet_id=snippet_id,
                description=description,
                scope=scope,
                path=path,
            )
        )

    return entries
