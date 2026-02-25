"""Unit tests for API auth and clearance dependencies."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from teleclaude.api.auth import CallerIdentity, require_clearance, verify_caller
from teleclaude.constants import ROLE_ORCHESTRATOR, ROLE_WORKER


def _request_with_headers(headers: dict[str, str] | None = None) -> Request:
    encoded = []
    for key, value in (headers or {}).items():
        encoded.append((key.lower().encode("utf-8"), value.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": encoded,
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_verify_caller_requires_identity() -> None:
    request = _request_with_headers()
    with pytest.raises(HTTPException) as excinfo:
        await verify_caller(request=request, x_caller_session_id=None, x_tmux_session=None)
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_caller_rejects_web_identity_headers_without_session_id() -> None:
    request = _request_with_headers(
        {
            "x-web-user-email": "admin@example.com",
            "x-web-user-role": "admin",
        }
    )
    with pytest.raises(HTTPException) as excinfo:
        await verify_caller(request=request, x_caller_session_id=None, x_tmux_session=None)
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_caller_rejects_unknown_session_id() -> None:
    request = _request_with_headers()
    with patch("teleclaude.api.auth.db.get_session", new_callable=AsyncMock, return_value=None):
        with pytest.raises(HTTPException) as excinfo:
            await verify_caller(request=request, x_caller_session_id="missing")
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_caller_rejects_tmux_mismatch() -> None:
    request = _request_with_headers()
    session = SimpleNamespace(
        tmux_session_name="tc_expected",
        human_role="admin",
        session_metadata={},
        working_slug=None,
    )
    with patch("teleclaude.api.auth.db.get_session", new_callable=AsyncMock, return_value=session):
        with pytest.raises(HTTPException) as excinfo:
            await verify_caller(
                request=request,
                x_caller_session_id="sess-1",
                x_tmux_session="tc_other",
            )
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_caller_reads_system_role_from_session_metadata() -> None:
    request = _request_with_headers()
    session = SimpleNamespace(
        tmux_session_name="tc_expected",
        human_role="admin",
        session_metadata={"system_role": ROLE_ORCHESTRATOR},
        working_slug="any-slug",
    )
    with patch("teleclaude.api.auth.db.get_session", new_callable=AsyncMock, return_value=session):
        identity = await verify_caller(
            request=request,
            x_caller_session_id="sess-1",
            x_tmux_session="tc_expected",
        )
    assert identity.system_role == ROLE_ORCHESTRATOR


@pytest.mark.asyncio
async def test_verify_caller_derives_worker_from_working_slug() -> None:
    request = _request_with_headers()
    session = SimpleNamespace(
        tmux_session_name="tc_expected",
        human_role="member",
        session_metadata={},
        working_slug="my-work-item",
    )
    with patch("teleclaude.api.auth.db.get_session", new_callable=AsyncMock, return_value=session):
        identity = await verify_caller(
            request=request,
            x_caller_session_id="sess-1",
            x_tmux_session="tc_expected",
        )
    assert identity.system_role == ROLE_WORKER


@pytest.mark.asyncio
async def test_require_clearance_denies_excluded_tool() -> None:
    check = require_clearance("teleclaude__start_session")
    identity = CallerIdentity(
        session_id="sess-1",
        system_role=ROLE_WORKER,
        human_role="admin",
        tmux_session_name="tc_1",
    )
    with pytest.raises(HTTPException) as excinfo:
        await check(identity=identity)
    assert excinfo.value.status_code == 403
