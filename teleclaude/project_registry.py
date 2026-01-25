"""Project context index registry stored in system settings."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

PROJECT_INDEXES_KEY = "project_indexes"


def load_project_indexes(db_path: Path) -> dict[str, str]:
    """Load project index registry from system_settings."""
    if not db_path.exists():
        logger.warning("Registry database missing", path=str(db_path))
        return {}

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (PROJECT_INDEXES_KEY,),
        )
        row = cursor.fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            logger.error("Invalid registry JSON")
            return {}
        if not isinstance(data, dict):
            return {}
        filtered: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, str):
                filtered[key] = value
        return filtered


def save_project_indexes(db_path: Path, indexes: dict[str, str]) -> None:
    """Persist project index registry to system_settings."""
    payload = json.dumps(indexes)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (PROJECT_INDEXES_KEY, payload),
        )
        conn.commit()


def register_project_index(db_path: Path, project_root: Path, index_path: Path) -> dict[str, str]:
    """Register or update a project index path."""
    indexes = load_project_indexes(db_path)
    indexes[str(project_root.resolve())] = str(index_path.resolve())
    save_project_indexes(db_path, indexes)
    return indexes
