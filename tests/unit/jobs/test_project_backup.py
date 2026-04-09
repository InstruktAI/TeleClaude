from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

from jobs import project_backup


def test_export_sqlite_snapshot_copies_data(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "snapshot.db"

    with sqlite3.connect(source) as conn:
        conn.execute("create table items (name text)")
        conn.execute("insert into items (name) values ('alpha')")
        conn.commit()

    project_backup._export_sqlite_snapshot(source, destination)

    with sqlite3.connect(destination) as conn:
        rows = conn.execute("select name from items").fetchall()

    assert rows == [("alpha",)]


def test_build_upload_target_uses_default_prefix(monkeypatch: object, tmp_path: Path) -> None:
    archive = tmp_path / "backup.tar.gz"

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_S3_HOST", "ams3.digitaloceanspaces.com")
    monkeypatch.setenv("AWS_S3_REGION", "ams3")
    monkeypatch.setenv("AWS_S3_BUCKET", "itsup")

    target = project_backup._build_upload_target(archive)

    assert target is not None
    assert target.endpoint_url == "https://ams3.digitaloceanspaces.com"
    assert target.bucket == "itsup"
    assert target.key == f"teleclaude/TeleClaude/{archive.name}"


def test_create_archive_includes_snapshot_and_manifest(tmp_path: Path) -> None:
    source = tmp_path / "todos.db"
    archive = tmp_path / "backup.tar.gz"

    with sqlite3.connect(source) as conn:
        conn.execute("create table items (name text)")
        conn.execute("insert into items (name) values ('alpha')")
        conn.commit()

    project_backup._create_archive(source, archive)

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()

    assert "todos.db" in names
    assert "manifest.json" in names
