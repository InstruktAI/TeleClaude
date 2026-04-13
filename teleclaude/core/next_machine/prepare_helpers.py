"""DB-backed artifact staleness detection for the prepare loop.

The prepare lifecycle refreshes digests and re-routes downstream review
verdicts when an upstream artifact diverges from its stamped digest. This
module owns the cascade definition and the DB-backed staleness check
consumed by :mod:`prepare` on every loop iteration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

# Canonical cascade order for staleness detection. Upstream changes invalidate
# all downstream review verdicts.
_ARTIFACT_CASCADE: list[tuple[str, str]] = [
    ("input", "input.md"),
    ("requirements", "requirements.md"),
    ("implementation_plan", "implementation-plan.md"),
]


async def check_artifact_staleness_db(todos_db: TodosDb, slug: str) -> list[str]:
    """Return stale artifact keys in cascade order using DB-stored digests.

    Compares stored digests on ``todo_state.artifacts`` against current
    digests in the ``todo_artifacts`` table. Returns an empty list when no
    upstream artifact has changed since its last stamp.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return []
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return []

    stale_from: int | None = None
    for idx, (key, filename) in enumerate(_ARTIFACT_CASCADE):
        entry = artifacts.get(key, {})
        if not isinstance(entry, dict):
            continue
        stored_digest = str(entry.get("digest", ""))
        if not stored_digest:
            continue
        db_name = filename.removesuffix(".md") if filename.endswith(".md") else key
        current = await todos_db.artifact_digest(slug, db_name)
        if current != stored_digest:
            stale_from = idx
            break

    if stale_from is None:
        return []

    return [key for key, _ in _ARTIFACT_CASCADE[stale_from:]]
