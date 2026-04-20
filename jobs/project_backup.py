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

The runner contract is minimal: print a serialized ``JobResult`` JSON object
to stdout and exit 0 on success or 1 on failure. This script is self-contained
and does not import anything from the ``jobs`` package — there is no PYTHONPATH
or ``sys.path`` manipulation at import time.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tarfile
import tempfile
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.client import Config
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
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

load_dotenv(_REPO_ROOT / ".env")


@dataclass(frozen=True)
class JobResult:
    """Structured result emitted to stdout for the cron runner to parse."""

    success: bool
    message: str
    items_processed: int = 0

    def to_json(self) -> str:
        """Serialize the result for the cron runner subprocess contract."""
        return json.dumps(
            {
                "success": self.success,
                "message": self.message,
                "items_processed": self.items_processed,
            },
            ensure_ascii=True,
        )


@dataclass(frozen=True)
class UploadTarget:
    """S3/Spaces upload destination resolved from environment variables."""

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


def _build_upload_target(archive_path: Path) -> UploadTarget | None:
    env = os.environ
    if any(not env.get(key) for key in _REQUIRED_UPLOAD_ENV_VARS):
        return None

    host = str(env["AWS_S3_HOST"]).strip()
    endpoint_url = host if host.startswith(("http://", "https://")) else f"https://{host}"
    prefix = str(env.get("TELECLAUDE_BACKUP_PREFIX", _DEFAULT_S3_PREFIX)).strip().strip("/")
    key = f"{prefix}/{archive_path.name}" if prefix else archive_path.name

    return UploadTarget(
        bucket=str(env["AWS_S3_BUCKET"]).strip(),
        endpoint_url=endpoint_url,
        region=str(env["AWS_S3_REGION"]).strip(),
        key=key,
    )


def _upload_archive(archive_path: Path, target: UploadTarget) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=target.endpoint_url,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=target.region,
        config=Config(signature_version="s3v4"),
    )
    client.upload_file(str(archive_path), target.bucket, target.key)


def run() -> JobResult:
    """Execute the backup workflow and return a JobResult."""
    _ensure_parent_dirs()
    archive_path = _BACKUPS_DIR / _archive_name()

    with tempfile.TemporaryDirectory(prefix="teleclaude-backup-") as temp_dir:
        sqlite_snapshot = Path(temp_dir) / "todos.db"
        _export_sqlite_snapshot(_PROJECT_TODO_DB, sqlite_snapshot)
        _create_archive(sqlite_snapshot, archive_path)

    upload_target = _build_upload_target(archive_path)
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


def main() -> int:
    """Entry point — run the backup and emit a JSON JobResult to stdout."""
    try:
        result = run()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        result = JobResult(success=False, message=str(exc))

    print(result.to_json())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
