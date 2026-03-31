"""Tests for httpx runtime debug tracing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.observability import httpx_runtime_debug


@pytest.mark.unit
def test_enable_httpx_async_client_tracing_is_idempotent() -> None:
    with (
        patch.object(httpx_runtime_debug.httpx.AsyncClient, "__init__") as init_mock,
        patch.object(httpx_runtime_debug.httpx.AsyncClient, "aclose") as aclose_mock,
    ):
        httpx_runtime_debug._STATE["enabled"] = False
        httpx_runtime_debug._STATE["original_init"] = None
        httpx_runtime_debug._STATE["original_aclose"] = None
        httpx_runtime_debug.enable_httpx_async_client_tracing()
        httpx_runtime_debug.enable_httpx_async_client_tracing()

    assert httpx_runtime_debug._STATE["enabled"] is True
    assert httpx_runtime_debug._STATE["original_init"] is init_mock
    assert httpx_runtime_debug._STATE["original_aclose"] is aclose_mock


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_aclose_logs_client_identity_on_closed_loop() -> None:
    client = object.__new__(httpx_runtime_debug.httpx.AsyncClient)

    async def raising_aclose(_self: object) -> None:
        raise RuntimeError("Event loop is closed")

    httpx_runtime_debug._STATE["enabled"] = False
    httpx_runtime_debug._STATE["original_init"] = None
    httpx_runtime_debug._STATE["original_aclose"] = None

    with (
        patch.object(httpx_runtime_debug.httpx.AsyncClient, "__init__", return_value=None),
        patch.object(httpx_runtime_debug.httpx.AsyncClient, "aclose", new=raising_aclose),
        patch.object(httpx_runtime_debug.logger, "error") as error_mock,
    ):
        httpx_runtime_debug.enable_httpx_async_client_tracing()
        traced_aclose = httpx_runtime_debug.httpx.AsyncClient.aclose

        with pytest.raises(RuntimeError, match="Event loop is closed"):
            await traced_aclose(client)

    _, kwargs = error_mock.call_args
    assert kwargs["client_type"] == "httpx.AsyncClient"
    assert kwargs["client_id"] == id(client)
