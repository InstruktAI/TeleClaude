"""Unit tests for durable operation receipt runtime."""

from __future__ import annotations

import asyncio

import pytest

from teleclaude.core.db import Db
from teleclaude.core.operations import emit_operation_progress
from teleclaude.core.operations.service import OperationsService
from teleclaude.core.task_registry import TaskRegistry


@pytest.fixture
async def operations_service(tmp_path, monkeypatch):
    test_db = Db(str(tmp_path / "operations-test.db"))
    await test_db.initialize()
    registry = TaskRegistry()
    service = OperationsService(
        db=test_db,
        task_registry=registry,
        poll_after_ms=1,
        heartbeat_interval_s=0.01,
        stale_after_s=0.01,
    )
    await service.start()
    try:
        yield service, test_db, registry
    finally:
        await registry.shutdown(timeout=0.1)
        await test_db.close()


@pytest.mark.asyncio
async def test_submit_dedupes_by_client_request_id(operations_service, monkeypatch):
    service, test_db, _registry = operations_service

    async def fake_next_work(_db, slug, cwd, caller_session_id):
        _ = (slug, cwd, caller_session_id)
        return "NEXT_WORK COMPLETE"

    monkeypatch.setattr("teleclaude.core.operations.service.next_work", fake_next_work)

    first = await service.submit_todo_work(
        slug="async-operation-receipts",
        cwd="/tmp/project",
        caller_session_id="caller-1",
        client_request_id="req-1",
    )
    for _ in range(50):
        current = await test_db.get_operation(str(first["operation_id"]))
        if current is not None and current.state == "completed":
            break
        await asyncio.sleep(0.01)

    second = await service.submit_todo_work(
        slug="async-operation-receipts",
        cwd="/tmp/project",
        caller_session_id="caller-1",
        client_request_id="req-1",
    )

    assert first["operation_id"] == second["operation_id"]


@pytest.mark.asyncio
async def test_submit_reattaches_matching_nonterminal_operation(operations_service, monkeypatch):
    service, test_db, _registry = operations_service
    release = asyncio.Event()

    async def fake_next_work(_db, slug, cwd, caller_session_id):
        _ = (slug, cwd, caller_session_id)
        await release.wait()
        return "NEXT_WORK COMPLETE"

    monkeypatch.setattr("teleclaude.core.operations.service.next_work", fake_next_work)

    first = await service.submit_todo_work(
        slug="async-operation-receipts",
        cwd="/tmp/project",
        caller_session_id="caller-1",
        client_request_id="req-1",
    )
    for _ in range(50):
        current = await test_db.get_operation(str(first["operation_id"]))
        if current is not None and current.state == "running":
            break
        await asyncio.sleep(0.01)

    second = await service.submit_todo_work(
        slug="async-operation-receipts",
        cwd="/tmp/project",
        caller_session_id="caller-1",
        client_request_id="req-2",
    )

    release.set()
    assert first["operation_id"] == second["operation_id"]


@pytest.mark.asyncio
async def test_service_start_marks_abandoned_nonterminal_operations_stale(tmp_path):
    test_db = Db(str(tmp_path / "operations-stale.db"))
    await test_db.initialize()
    await test_db.create_operation(
        operation_id="op-1",
        kind="todo_work",
        caller_session_id="caller-1",
        client_request_id="req-1",
        cwd="/tmp/project",
        slug="async-operation-receipts",
        payload_json='{"cwd": "/tmp/project", "slug": "async-operation-receipts"}',
        state="running",
    )

    registry = TaskRegistry()
    service = OperationsService(db=test_db, task_registry=registry)
    await service.start()

    row = await test_db.get_operation("op-1")

    assert row is not None
    assert row.state == "stale"
    assert row.error_text == "daemon restarted before operation completed"

    await registry.shutdown(timeout=0.1)
    await test_db.close()


@pytest.mark.asyncio
async def test_terminal_operation_keeps_latest_progress(operations_service, monkeypatch):
    service, test_db, _registry = operations_service

    async def fake_next_work(_db, slug, cwd, caller_session_id):
        _ = (slug, cwd, caller_session_id)
        emit_operation_progress("dispatch_decision", "error", "uncommitted_changes")
        return "UNCOMMITTED CHANGES"

    monkeypatch.setattr("teleclaude.core.operations.service.next_work", fake_next_work)

    receipt = await service.submit_todo_work(
        slug="async-operation-receipts",
        cwd="/tmp/project",
        caller_session_id="caller-1",
        client_request_id="req-final-progress",
    )

    for _ in range(50):
        current = await test_db.get_operation(str(receipt["operation_id"]))
        if current is not None and current.state == "completed":
            break
        await asyncio.sleep(0.01)

    row = await test_db.get_operation(str(receipt["operation_id"]))
    assert row is not None
    assert row.progress_phase == "dispatch_decision"
    assert row.progress_reason == "uncommitted_changes"
