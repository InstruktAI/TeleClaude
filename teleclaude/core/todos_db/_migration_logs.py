"""Migration decision logs for todo state upcycles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def _log_path(project_root: str) -> Path:
    return Path(project_root) / ".teleclaude" / "migration-logs" / "prepare-v2-v3.jsonl"


def _seen_slugs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        slug = payload.get("slug")
        if isinstance(slug, str):
            seen.add(slug)
    return seen


def record_v2_to_v3_migration(
    slug: str,
    *,
    from_lifecycle_phase: str,
    to_lifecycle_phase: str,
    kind: str,
    worktree_abandoned: bool,
    project_root: str,
) -> None:
    """Append one idempotent prepare-v2-to-v3 migration decision record."""
    path = _log_path(project_root)
    if slug in _seen_slugs(path):
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "slug": slug,
        "from_lifecycle_phase": from_lifecycle_phase,
        "to_lifecycle_phase": to_lifecycle_phase,
        "kind": kind,
        "worktree_abandoned": worktree_abandoned,
        "decision": (
            f"{from_lifecycle_phase} -> {to_lifecycle_phase}; "
            "prepare v3 is worktree-free, pair-free, and grounding-free"
        ),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


__all__ = ["record_v2_to_v3_migration"]
