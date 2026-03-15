from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.core import db_models
from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_create_operation_can_be_fetched_by_id_and_request_key(db: Db) -> None:
    created = await db.create_operation(
        operation_id="op-001",
        kind="build",
        caller_session_id="sess-001",
        client_request_id="req-001",
        cwd="/repo",
        slug="chartest-core-db",
        payload_json='{"step":"build"}',
        state="queued",
    )

    fetched = await db.get_operation("op-001")
    by_request = await db.get_operation_by_request(
        kind="build",
        caller_session_id="sess-001",
        client_request_id="req-001",
    )

    assert created.operation_id == "op-001"
    assert fetched is not None
    assert fetched.payload_json == '{"step":"build"}'
    assert by_request is not None
    assert by_request.operation_id == "op-001"


async def test_find_matching_nonterminal_operation_prefers_latest_matching_slug(db: Db) -> None:
    await db.create_operation(
        operation_id="op-old",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug="slug-a",
        payload_json="{}",
        state="queued",
    )
    await db.create_operation(
        operation_id="op-match",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug="slug-a",
        payload_json="{}",
        state="running",
    )
    await db.create_operation(
        operation_id="op-other-slug",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug="slug-b",
        payload_json="{}",
        state="running",
    )

    match = await db.find_matching_nonterminal_operation(
        kind="build",
        caller_session_id="sess-001",
        cwd="/repo",
        slug="slug-a",
    )
    no_slug_match = await db.find_matching_nonterminal_operation(
        kind="build",
        caller_session_id="sess-001",
        cwd="/repo",
        slug=None,
    )

    assert match is not None
    assert match.operation_id == "op-match"
    assert no_slug_match is None


async def test_claim_touch_and_progress_updates_only_running_operations(db: Db) -> None:
    await db.create_operation(
        operation_id="op-001",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="queued",
    )
    now_iso = datetime.now(UTC).isoformat()

    claimed = await db.claim_operation("op-001", now_iso=now_iso)
    await db.touch_operation("op-001", now_iso=now_iso)
    await db.update_operation_progress(
        "op-001",
        phase="tests",
        decision="continue",
        reason="queue claimed",
        now_iso=now_iso,
    )

    op = await db.get_operation("op-001")

    assert claimed is True
    assert op is not None
    assert op.state == "running"
    assert op.started_at == now_iso
    assert op.heartbeat_at == now_iso
    assert op.attempt_count == 1
    assert op.progress_phase == "tests"
    assert op.progress_decision == "continue"
    assert op.progress_reason == "queue claimed"


async def test_complete_and_fail_operations_record_terminal_metadata(db: Db) -> None:
    await db.create_operation(
        operation_id="op-complete",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="running",
    )
    await db.create_operation(
        operation_id="op-fail",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="running",
    )
    now_iso = datetime.now(UTC).isoformat()
    await db.complete_operation("op-complete", "done", now_iso=now_iso)
    await db.fail_operation("op-fail", "boom", now_iso=now_iso, state="cancelled")

    completed = await db.get_operation("op-complete")
    failed = await db.get_operation("op-fail")

    assert completed is not None
    assert completed.state == "completed"
    assert completed.result_text == "done"
    assert completed.error_text is None
    assert completed.completed_at == now_iso
    assert failed is not None
    assert failed.state == "cancelled"
    assert failed.error_text == "boom"
    assert failed.completed_at == now_iso


async def test_stale_helpers_mark_only_nonterminal_or_old_running_operations(db: Db) -> None:
    await db.create_operation(
        operation_id="op-queued",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="queued",
    )
    await db.create_operation(
        operation_id="op-running",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="running",
    )
    await db.create_operation(
        operation_id="op-done",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="completed",
    )

    stale_count = await db.mark_nonterminal_operations_stale(error_text="restart")
    running = await db.get_operation("op-running")
    queued = await db.get_operation("op-queued")
    done = await db.get_operation("op-done")

    assert stale_count == 2
    assert running is not None and running.state == "stale"
    assert queued is not None and queued.state == "stale"
    assert done is not None and done.state == "completed"

    await db.create_operation(
        operation_id="op-old-running",
        kind="build",
        caller_session_id="sess-001",
        client_request_id=None,
        cwd="/repo",
        slug=None,
        payload_json="{}",
        state="running",
    )
    async with db._session() as session:
        row = await session.get(db_models.Operation, "op-old-running")
        assert row is not None
        row.heartbeat_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        session.add(row)
        await session.commit()

    expired_count = await db.expire_stale_operations(
        older_than_iso=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        error_text="timeout",
    )
    expired = await db.get_operation("op-old-running")

    assert expired_count == 1
    assert expired is not None
    assert expired.state == "stale"
    assert expired.error_text == "timeout"
