"""Config-owned notification for changes to identity declarations, and the files those declarations live in."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, PEOPLE_DIR, PROJECTS_MANIFEST_PATH, ConfigFileName
from teleclaude.project_manifest import load_roots

_SUBSCRIBERS: set[Callable[[], None]] = set()


def subscribe_declaration_changes(callback: Callable[[], None]) -> None:
    """Register a synchronous consumer for membership or ownership changes."""
    _SUBSCRIBERS.add(callback)


def unsubscribe_declaration_changes(callback: Callable[[], None]) -> None:
    """Remove a consumer that no longer holds live identity state."""
    _SUBSCRIBERS.discard(callback)


def identity_declaration_watch_paths() -> list[Path]:
    """Return config declarations whose changes can alter identity reach."""
    paths = {GLOBAL_CONFIG_PATH, PEOPLE_DIR, COMPANIES_ROOT, PROJECTS_MANIFEST_PATH}
    if PEOPLE_DIR.is_dir():
        for person_dir in PEOPLE_DIR.iterdir():
            paths.add(person_dir)
            paths.add(person_dir / ConfigFileName.OVERLAY)
    if COMPANIES_ROOT.is_dir():
        for company_dir in COMPANIES_ROOT.iterdir():
            paths.add(company_dir)
            paths.add(company_dir / ConfigFileName.OVERLAY)
    for project_root in load_roots():
        paths.add(project_root)
        paths.add(project_root / ConfigFileName.OVERLAY)
    return sorted(paths)


def identity_declaration_documents() -> list[Path]:
    """Return the watched configuration declarations that exist as files."""
    return [
        path for path in identity_declaration_watch_paths() if path.name == ConfigFileName.OVERLAY and path.is_file()
    ]


def publish_declaration_changes() -> None:
    """Notify consumers after config has refreshed its published answers."""
    for callback in tuple(_SUBSCRIBERS):
        callback()
