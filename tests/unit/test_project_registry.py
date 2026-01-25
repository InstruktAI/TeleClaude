from __future__ import annotations

import sqlite3
from pathlib import Path

from teleclaude.project_registry import load_project_indexes, register_project_index


def _init_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.commit()


def test_register_project_index_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "teleclaude.db"
    _init_db(db_path)

    project_root = tmp_path / "project"
    index_path = project_root / "docs" / "index.yaml"
    project_root.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("snippets: []\n", encoding="utf-8")

    register_project_index(db_path, project_root, index_path)
    indexes = load_project_indexes(db_path)

    assert indexes[str(project_root.resolve())] == str(index_path.resolve())
