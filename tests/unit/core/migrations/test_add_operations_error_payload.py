from __future__ import annotations

import importlib

import aiosqlite
import pytest

add_operations_error_payload = importlib.import_module("teleclaude.core.migrations.046_add_operations_error_payload")
ERROR_PAYLOAD_COLUMN = add_operations_error_payload.ERROR_PAYLOAD_COLUMN


async def _operation_columns(db: aiosqlite.Connection) -> set[str]:
    async with db.execute("SELECT name FROM pragma_table_info('operations')") as cursor:
        rows = await cursor.fetchall()
    return {str(row[0]) for row in rows}


@pytest.mark.asyncio
async def test_add_operations_error_payload_adds_nullable_column_idempotently() -> None:
    db = await aiosqlite.connect(":memory:")
    try:
        await db.execute("""
            CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                caller_session_id TEXT NOT NULL,
                cwd TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                state TEXT NOT NULL,
                error_text TEXT
            )
        """)
        await db.execute("""
            INSERT INTO operations (
                operation_id,
                kind,
                caller_session_id,
                cwd,
                payload_json,
                state,
                error_text
            )
            VALUES (
                'op-1',
                'todo_remove',
                'session-1',
                '/repo',
                '{}',
                'failed',
                'legacy failure'
            )
        """)
        await db.commit()

        await add_operations_error_payload.up(db)
        await add_operations_error_payload.up(db)

        async with db.execute("SELECT error_payload FROM operations WHERE operation_id = 'op-1'") as cursor:
            row = await cursor.fetchone()

        assert ERROR_PAYLOAD_COLUMN in await _operation_columns(db)
        assert row == (None,)
    finally:
        await db.close()
