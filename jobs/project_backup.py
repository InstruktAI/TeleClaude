#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "boto3>=1.34.0",
#     "python-dotenv>=1.2.1",
# ]
# ///
"""Create a project-local TeleClaude backup archive and optionally upload it.

This job exports a consistent snapshot of the project-local todo database,
packages it with a small manifest, and writes the resulting tar.gz archive to
``.teleclaude/backups``.

If the standard S3/Spaces environment variables are present, the archive is
also uploaded to that bucket.

The module exposes ``JOB`` for in-process runner discovery and keeps the
standalone CLI path through ``run_job_cli``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.client import Config
from dotenv import dotenv_values

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jobs.base import Job, JobResult, run_job_cli

_PROJECT_TODO_DB = _REPO_ROOT / ".teleclaude" / "todos.db"
_BACKUPS_DIR = _REPO_ROOT / ".teleclaude" / "backups"
_ARCHIVE_PREFIX = "teleclaude-todos-backup"
_DEFAULT_S3_PREFIX = "teleclaude/TeleClaude"
_REQUIRED_UPLOAD_ENV_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_S3_HOST",
    "AWS_S3_REGION",
    "AWS_S3_BUCKET",
)


@dataclass(frozen=True)
class UploadTarget:
    """S3/Spaces upload destination resolved from environment variables."""

    access_key_id: str
    secret_access_key: str
    bucket: str
    endpoint_url: str
    region: str
    key: str


def _timestamp_slug(now: datetime | None = None) -> str:
    effective_now = now or datetime.now(UTC)
    return effective_now.astimezone(UTC).strftime("%Y%m%d-%H%M%SZ")


def _archive_name(now: datetime | None = None) -> str:
    return f"{_ARCHIVE_PREFIX}-{_timestamp_slug(now)}.tar.gz"


def _ensure_parent_dirs() -> None:
    _PROJECT_TODO_DB.parent.mkdir(parents=True, exist_ok=True)
    _BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _load_backup_env() -> dict[str, str]:
    dotenv_env = {key: value for key, value in dotenv_values(_REPO_ROOT / ".env").items() if value is not None}
    return dotenv_env | dict(os.environ)


def _export_sqlite_snapshot(source_db: Path, destination_db: Path) -> None:
    if not source_db.exists():
        raise FileNotFoundError(f"Todo database not found: {source_db}")

    with sqlite3.connect(source_db) as source_conn:
        with sqlite3.connect(destination_db) as dest_conn:
            source_conn.backup(dest_conn)


def _manifest_payload(
    archive_name: str,
    sqlite_name: str,
    now: datetime | None = None,
) -> dict[str, object]:
    created_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    return {
        "kind": "teleclaude-project-backup",
        "created_at": created_at,
        "project_name": "TeleClaude",
        "repo_root": str(_REPO_ROOT),
        "artifacts": {
            "sqlite_backup": sqlite_name,
            "archive": archive_name,
        },
    }


def _create_archive(source_db: Path, archive_path: Path, now: datetime | None = None) -> None:
    manifest = _manifest_payload(archive_path.name, source_db.name, now=now)
    with tempfile.TemporaryDirectory(prefix="teleclaude-backup-manifest-") as temp_dir:
        manifest_path = Path(temp_dir) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(source_db, arcname=source_db.name)
            tar.add(manifest_path, arcname="manifest.json")


def _build_upload_target(archive_path: Path, env: Mapping[str, str]) -> UploadTarget | None:
    required_values = {key: env.get(key) for key in _REQUIRED_UPLOAD_ENV_VARS}
    if any(not value for value in required_values.values()):
        return None

    access_key_id = required_values["AWS_ACCESS_KEY_ID"]
    secret_access_key = required_values["AWS_SECRET_ACCESS_KEY"]
    host = required_values["AWS_S3_HOST"]
    region = required_values["AWS_S3_REGION"]
    bucket = required_values["AWS_S3_BUCKET"]
    if access_key_id is None or secret_access_key is None or host is None or region is None or bucket is None:
        return None

    host = host.strip()
    endpoint_url = host if host.startswith(("http://", "https://")) else f"https://{host}"
    prefix = str(env.get("TELECLAUDE_BACKUP_PREFIX", _DEFAULT_S3_PREFIX)).strip().strip("/")
    key = f"{prefix}/{archive_path.name}" if prefix else archive_path.name

    return UploadTarget(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        bucket=bucket.strip(),
        endpoint_url=endpoint_url,
        region=region.strip(),
        key=key,
    )


def _upload_archive(archive_path: Path, target: UploadTarget) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=target.endpoint_url,
        aws_access_key_id=target.access_key_id,
        aws_secret_access_key=target.secret_access_key,
        region_name=target.region,
        config=Config(signature_version="s3v4"),
    )
    client.upload_file(str(archive_path), target.bucket, target.key)


class ProjectBackupJob(Job):
    """Back up the project-local todo database."""

    name = "project_backup"

    def run(self) -> JobResult:
        """Execute the backup workflow and return a JobResult."""
        backup_env = _load_backup_env()
        _ensure_parent_dirs()
        archive_path = _BACKUPS_DIR / _archive_name()

        with tempfile.TemporaryDirectory(prefix="teleclaude-backup-") as temp_dir:
            sqlite_snapshot = Path(temp_dir) / "todos.db"
            _export_sqlite_snapshot(_PROJECT_TODO_DB, sqlite_snapshot)
            _create_archive(sqlite_snapshot, archive_path)

        upload_target = _build_upload_target(archive_path, backup_env)
        upload_message = ""
        items_processed = 1

        if upload_target is not None:
            _upload_archive(archive_path, upload_target)
            upload_message = f"; uploaded to s3://{upload_target.bucket}/{upload_target.key}"
            items_processed = 2

        return JobResult(
            success=True,
            message=f"Created backup archive at {archive_path}{upload_message}",
            items_processed=items_processed,
        )


JOB = ProjectBackupJob()


if __name__ == "__main__":
    raise SystemExit(run_job_cli(JOB))
