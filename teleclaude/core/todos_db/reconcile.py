"""Reconcile filesystem todos with todos.db — idempotent, timestamp-aware.

Compares every artifact and state entry between filesystem and DB.
For each item, the newer source wins. Safe to run repeatedly.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

_ARTIFACT_EXTENSIONS = frozenset({".md"})


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_db_timestamp(ts: str | None) -> float:
    """Parse an ISO 8601 timestamp from the DB into epoch seconds. Returns 0 if unparsable."""
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


async def _ensure_slug_in_roadmap(slug: str, todos_db: TodosDb, counts: dict[str, int]) -> None:
    """Ensure artifact/state writes have a roadmap parent without inventing one in write_artifact()."""
    if await todos_db.slug_in_roadmap(slug):
        return
    if await todos_db.add_to_roadmap(slug):
        counts["roadmap_added"] += 1


async def reconcile_filesystem_to_db(project_root: str, todos_db: TodosDb) -> dict[str, int]:
    """Reconcile filesystem todos with the database.

    For each slug found on the filesystem (todos/{slug}/ and trees/{slug}/todos/{slug}/):
    - State: compare filesystem state.yaml mtime vs DB updated_at. Newer wins.
    - Artifacts: compare each .md file's mtime vs DB artifact updated_at. Newer wins.
    - Roadmap: ensure every filesystem slug has a roadmap entry.

    Returns counts: {state_updated, state_inserted, artifacts_updated, artifacts_inserted, roadmap_added}.
    """
    root = Path(project_root)
    todos_dir = root / "todos"
    worktrees_dir = root / WORKTREE_DIR

    counts = {
        "state_updated": 0,
        "state_inserted": 0,
        "artifacts_updated": 0,
        "artifacts_inserted": 0,
        "roadmap_added": 0,
    }

    if not todos_dir.is_dir():
        return counts

    # Collect all slug directories from all sources
    slug_dirs: dict[str, list[Path]] = {}

    # Main todos/ directory
    for entry in sorted(todos_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            slug_dirs.setdefault(entry.name, []).append(entry)

    # Worktrees: trees/{slug}/todos/{slug}/
    if worktrees_dir.is_dir():
        for wt_entry in sorted(worktrees_dir.iterdir()):
            if not wt_entry.is_dir() or wt_entry.name.startswith((".", "_")):
                continue
            wt_todo = wt_entry / "todos" / wt_entry.name
            if wt_todo.is_dir():
                slug_dirs.setdefault(wt_entry.name, []).append(wt_todo)

    # Reconcile each slug
    for slug, dirs in slug_dirs.items():
        await _reconcile_slug_state(slug, dirs, todos_db, counts)
        await _reconcile_slug_artifacts(slug, dirs, todos_db, counts)

    logger.info(
        "Reconciliation complete: %s",
        ", ".join(f"{k}={v}" for k, v in counts.items() if v > 0) or "no changes",
    )
    return counts


async def _reconcile_slug_state(  # pylint: disable=too-many-locals
    slug: str,
    dirs: list[Path],
    todos_db: TodosDb,
    counts: dict[str, int],
) -> None:
    """Reconcile state.yaml vs DB state for a slug. Newest wins."""
    # Find the newest state.yaml across all dirs
    best_path: Path | None = None
    best_mtime: float = 0.0

    for d in dirs:
        state_path = d / "state.yaml"
        if state_path.exists():
            mtime = state_path.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_path = state_path

    if best_path is None:
        return

    # Compare with DB
    db_state = await todos_db.read_state(slug)
    if db_state is not None:
        # Get DB timestamp
        conn = todos_db._sync_conn()  # pylint: disable=protected-access
        try:
            # Resolve slug to id for precise lookup
            id_row = conn.execute(
                "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
                (slug,),
            ).fetchone()
            lookup_id = id_row[0] if id_row else slug
            row = conn.execute(
                "SELECT updated_at FROM todo_state WHERE id = ?",  # guard: raw-sql
                (lookup_id,),
            ).fetchone()
            db_mtime = _parse_db_timestamp(row[0]) if row else 0.0
        finally:
            conn.close()

        if best_mtime <= db_mtime:
            return  # DB is newer or same — skip

    # Filesystem is newer — read and upsert
    try:
        fs_state = yaml.safe_load(best_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Failed to read state for %s: %s", slug, exc)
        return

    if not isinstance(fs_state, dict):
        return

    # write_state requires an active roadmap entry; ensure one exists for slugs
    # not covered by roadmap.yaml (e.g. worktree-only slugs)
    await _ensure_slug_in_roadmap(slug, todos_db, counts)
    await todos_db.write_state(slug, fs_state)
    if db_state is None:
        counts["state_inserted"] += 1
        logger.info("Inserted state for %s from %s", slug, best_path)
    else:
        counts["state_updated"] += 1
        logger.info("Updated state for %s from %s (filesystem newer)", slug, best_path)


async def _reconcile_slug_artifacts(  # pylint: disable=too-many-locals
    slug: str,
    dirs: list[Path],
    todos_db: TodosDb,
    counts: dict[str, int],
) -> None:
    """Reconcile each .md artifact file vs DB artifact. Per-artifact, newest wins."""
    # Collect best (newest) version of each artifact across all dirs
    best_artifacts: dict[str, tuple[Path, float]] = {}

    for d in dirs:
        for f in d.iterdir():
            if not f.is_file() or f.suffix not in _ARTIFACT_EXTENSIONS:
                continue
            name = f.stem
            mtime = f.stat().st_mtime
            if name not in best_artifacts or mtime > best_artifacts[name][1]:
                best_artifacts[name] = (f, mtime)

    if not best_artifacts:
        return

    # Get DB artifact timestamps
    conn = todos_db._sync_conn()  # pylint: disable=protected-access
    try:
        # Resolve slug to id for precise lookup
        id_row = conn.execute(
            "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
        lookup_id = id_row[0] if id_row else slug
        db_rows = conn.execute(
            "SELECT name, updated_at, digest FROM todo_artifacts WHERE id = ?",  # guard: raw-sql
            (lookup_id,),
        ).fetchall()
    finally:
        conn.close()

    db_artifacts: dict[str, tuple[float, str]] = {}
    for row in db_rows:
        db_artifacts[row[0]] = (_parse_db_timestamp(row[1]), row[2])

    # Compare each artifact
    for name, (path, fs_mtime) in best_artifacts.items():
        db_entry = db_artifacts.get(name)

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        fs_digest = _sha256(content)

        if db_entry is not None:
            db_mtime, db_digest = db_entry
            # Skip if DB is newer or content is identical
            if fs_mtime <= db_mtime or fs_digest == db_digest:
                continue
            await _ensure_slug_in_roadmap(slug, todos_db, counts)
            await todos_db.write_artifact(slug, name, content, updated_by="reconcile")
            counts["artifacts_updated"] += 1
            logger.info("Updated artifact %s/%s (filesystem newer)", slug, name)
        else:
            # Not in DB — insert
            await _ensure_slug_in_roadmap(slug, todos_db, counts)
            await todos_db.write_artifact(slug, name, content, updated_by="reconcile")
            counts["artifacts_inserted"] += 1
            logger.info("Inserted artifact %s/%s", slug, name)
