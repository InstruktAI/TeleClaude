"""One-time migration: import existing todos/ filesystem data into todos.db."""

from __future__ import annotations

from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

_ARTIFACT_EXTENSIONS = (".md",)


async def migrate_todos_to_db(project_root: str, todos_db: TodosDb) -> None:
    """Import existing filesystem todos into the database.

    Idempotent: skips slugs that already have state in the DB.
    Imports state.yaml, all .md artifacts, and roadmap entries.
    """
    root = Path(project_root)
    todos_dir = root / "todos"
    if not todos_dir.is_dir():
        logger.info("No todos/ directory found at %s, nothing to migrate", project_root)
        return

    # Import roadmap
    roadmap_path = todos_dir / "roadmap.yaml"
    if roadmap_path.exists():
        await _import_roadmap(roadmap_path, todos_db)

    # Import delivered.yaml
    delivered_path = todos_dir / "delivered.yaml"
    if delivered_path.exists():
        await _import_delivered(delivered_path, todos_db)

    # Import each slug
    for entry in sorted(todos_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        slug = entry.name
        await _import_slug(entry, slug, todos_db)

    logger.info("Migration complete for %s", project_root)


async def _import_roadmap(roadmap_path: Path, todos_db: TodosDb) -> None:
    """Import roadmap.yaml entries into the roadmap table."""
    content = roadmap_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return

    for entry in raw:
        if not isinstance(entry, dict) or "slug" not in entry:
            continue
        slug = entry["slug"]
        if await todos_db.slug_in_roadmap(slug):
            continue

        group = entry.get("group")
        after = entry.get("after", [])
        description = entry.get("description")
        await todos_db.add_to_roadmap(
            slug,
            group_slug=group,
            after=after if isinstance(after, list) else None,
            description=description,
        )
    logger.info("Imported %d roadmap entries", len(raw))


async def _import_delivered(delivered_path: Path, todos_db: TodosDb) -> None:
    """Import delivered.yaml entries into the roadmap table with status='delivered'."""
    content = delivered_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return

    for entry in raw:
        if not isinstance(entry, dict) or "slug" not in entry:
            continue
        slug = entry["slug"]
        if await todos_db.slug_in_roadmap(slug):
            continue

        # Add to roadmap first, then deliver
        children = entry.get("children")
        await todos_db.add_to_roadmap(slug)
        await todos_db.deliver(
            slug,
            commit=entry.get("commit"),
            children=children if isinstance(children, list) else None,
        )
    logger.info("Imported %d delivered entries", len(raw))


async def _import_slug(slug_dir: Path, slug: str, todos_db: TodosDb) -> None:
    """Import a single slug's state and artifacts."""
    # Skip if already migrated
    existing = await todos_db.read_state(slug)
    if existing is not None:
        logger.debug("Slug %s already in DB, skipping", slug)
        return

    # State
    state_path = slug_dir / "state.yaml"
    if state_path.exists():
        state_content = state_path.read_text(encoding="utf-8")
        state = yaml.safe_load(state_content)
        if isinstance(state, dict):
            await todos_db.write_state(slug, state)
            logger.debug("Imported state for %s", slug)

    # Artifacts
    for artifact_path in sorted(slug_dir.iterdir()):
        if artifact_path.suffix not in _ARTIFACT_EXTENSIONS:
            continue
        name = artifact_path.stem
        content = artifact_path.read_text(encoding="utf-8")
        await todos_db.write_artifact(slug, name, content)
        logger.debug("Imported artifact %s/%s", slug, name)
