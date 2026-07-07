"""Functional coverage for windowed batch write and dispatch contracts."""

from __future__ import annotations

import multiprocessing
import sqlite3
import warnings
from pathlib import Path
from typing import Protocol

import pytest

from teleclaude.core import db_models
from teleclaude.core.db.connection_factory import create_sync_db_engine, get_outbox_db_path

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/agent_runtime/windowed-batch-write-and-dispatch"
_BOOTSTRAP_PROCESS_COUNT = 8


class _Barrier(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...


def _bootstrap_outbox_schema(db_path: str, barrier: _Barrier) -> None:
    barrier.wait(timeout=5)
    engine = create_sync_db_engine(db_path)
    engine.dispose()


@pytest.mark.spec(_SPEC, "UC-WBW-1")
def test_concurrent_outbox_schema_bootstrap_is_idempotent(tmp_path: Path) -> None:
    outbox_db_path = get_outbox_db_path(tmp_path)
    with sqlite3.connect(outbox_db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")

    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(_BOOTSTRAP_PROCESS_COUNT)
    processes = [
        context.Process(target=_bootstrap_outbox_schema, args=(str(outbox_db_path), barrier))
        for _ in range(_BOOTSTRAP_PROCESS_COUNT)
    ]

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*use of fork.*")
            for process in processes:
                process.start()

        for process in processes:
            process.join(timeout=5)

        for process in processes:
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)

    with sqlite3.connect(outbox_db_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = ?",
                ("table",),
            )
        }

    assert db_models.HookOutbox.__tablename__ in table_names
