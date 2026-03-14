"""Unit tests for teleclaude.events.sandbox.runner."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.sandbox.protocol import (
    SandboxRequest,
    read_frame,
    request_to_dict,
    response_from_dict,
    write_frame,
)
from teleclaude.events.sandbox.runner import (
    SandboxRunner,
    _build_catalog_from_snapshot,
    _load_cartridge_module,
)

# ---------------------------------------------------------------------------
# _load_cartridge_module
# ---------------------------------------------------------------------------


def test_load_cartridge_module_missing_file():
    with pytest.raises(FileNotFoundError, match="Cartridge not found"):
        _load_cartridge_module("/nonexistent/dir", "missing")


def test_load_cartridge_module_no_process_callable():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "no_fn.py").write_text("x = 1\n")
        module = _load_cartridge_module(tmpdir, "no_fn")
        assert not callable(getattr(module, "process", None))


def test_load_cartridge_module_loads_callable():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "echo_cart.py").write_text("async def process(envelope, ctx):\n    return envelope\n")
        module = _load_cartridge_module(tmpdir, "echo_cart")
        assert callable(getattr(module, "process", None))


def test_load_cartridge_module_syntax_error_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "bad_syntax.py").write_text("def broken(\n")
        with pytest.raises(SyntaxError):
            _load_cartridge_module(tmpdir, "bad_syntax")


def test_load_cartridge_module_returns_fresh_object_each_call():
    """Each call returns a distinct module object; no sys.modules reuse."""
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "cart_obj.py").write_text("VALUE = 1\n")
        mod1 = _load_cartridge_module(tmpdir, "cart_obj")
        mod2 = _load_cartridge_module(tmpdir, "cart_obj")
        assert mod1 is not mod2
        assert mod1.VALUE == 1
        assert mod2.VALUE == 1


# ---------------------------------------------------------------------------
# _build_catalog_from_snapshot
# ---------------------------------------------------------------------------


def test_build_catalog_empty_snapshot():
    catalog = _build_catalog_from_snapshot([])
    assert catalog.list_all() == []


def test_build_catalog_valid_entry():
    # EventLevel.OPERATIONAL == 1 (IntEnum)
    snapshot = [
        {
            "event_type": "test.event",
            "description": "A test event",
            "default_level": 1,
            "domain": "test",
        }
    ]
    catalog = _build_catalog_from_snapshot(snapshot)
    schema = catalog.get("test.event")
    assert schema is not None
    assert schema.domain == "test"


def test_build_catalog_skips_malformed_entries():
    snapshot = [
        {"event_type": "valid.event", "description": "ok", "default_level": 1, "domain": "x"},
        {"bad_field": "no event_type"},
    ]
    catalog = _build_catalog_from_snapshot(snapshot)
    # Only the valid entry is registered; malformed entry is skipped with a warning
    assert len(catalog.list_all()) == 1
    assert catalog.get("valid.event") is not None


# ---------------------------------------------------------------------------
# SandboxRunner._handle_client (via socket pair)
# ---------------------------------------------------------------------------


async def _run_single_request(
    tmpdir: str,
    request_dict: dict,
) -> dict:
    """Spin up SandboxRunner, send one request, return the raw response dict."""
    sock_path = str(Path(tmpdir) / "test.sock")

    shutdown = asyncio.Event()
    runner = SandboxRunner(socket_path=sock_path, cartridges_dir=tmpdir)

    server_task = asyncio.create_task(runner.start(shutdown))
    # Wait briefly for socket to be created
    for _ in range(50):
        if Path(sock_path).exists():
            break
        await asyncio.sleep(0.01)

    try:
        reader, writer = await asyncio.open_unix_connection(sock_path)
        await write_frame(writer, request_dict)
        response = await asyncio.wait_for(read_frame(reader), timeout=5.0)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return response
    finally:
        shutdown.set()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            server_task.cancel()


@pytest.mark.asyncio
async def test_ping_handler_returns_ok():
    with tempfile.TemporaryDirectory() as tmpdir:
        req = request_to_dict(SandboxRequest(cartridge_name="__ping__", envelope={}, catalog_snapshot=[]))
        resp = await _run_single_request(tmpdir, req)
        parsed = response_from_dict(resp)
        assert parsed.error is None


@pytest.mark.asyncio
async def test_handle_client_missing_cartridge_returns_error():
    """Runner returns an error response for a cartridge that does not exist on disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from datetime import datetime

        from teleclaude.events.envelope import EventEnvelope

        env = EventEnvelope(
            event="test.event",
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            description="test",
            visibility=EventVisibility.LOCAL,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        )
        req = request_to_dict(
            SandboxRequest(
                cartridge_name="nonexistent_cart",
                envelope=env.to_stream_dict(),
                catalog_snapshot=[],
            )
        )
        resp = await _run_single_request(tmpdir, req)
        parsed = response_from_dict(resp)
        assert parsed.error is not None
        assert parsed.envelope is None


@pytest.mark.asyncio
async def test_handle_client_cartridge_no_process_fn_returns_error():
    """Runner returns an error response when cartridge module lacks a callable 'process'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from datetime import datetime

        from teleclaude.events.envelope import EventEnvelope

        Path(tmpdir, "no_process.py").write_text("x = 42\n")

        env = EventEnvelope(
            event="test.event",
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            description="test",
            visibility=EventVisibility.LOCAL,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        )
        req = request_to_dict(
            SandboxRequest(
                cartridge_name="no_process",
                envelope=env.to_stream_dict(),
                catalog_snapshot=[],
            )
        )
        resp = await _run_single_request(tmpdir, req)
        parsed = response_from_dict(resp)
        assert parsed.error is not None
        assert parsed.envelope is None


@pytest.mark.asyncio
async def test_handle_client_cartridge_returning_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        from datetime import datetime

        from teleclaude.events.envelope import EventEnvelope

        Path(tmpdir, "null_cart.py").write_text("async def process(envelope, ctx):\n    return None\n")

        env = EventEnvelope(
            event="test.event",
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            description="test",
            visibility=EventVisibility.LOCAL,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        )
        req = request_to_dict(
            SandboxRequest(
                cartridge_name="null_cart",
                envelope=env.to_stream_dict(),
                catalog_snapshot=[],
            )
        )
        resp = await _run_single_request(tmpdir, req)
        parsed = response_from_dict(resp)
        assert parsed.error is None
        assert parsed.envelope is None


@pytest.mark.asyncio
async def test_handle_client_timeout_returns_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        from datetime import datetime

        from teleclaude.events.envelope import EventEnvelope

        # Cartridge that sleeps longer than the patched timeout
        Path(tmpdir, "slow_cart.py").write_text(
            "import asyncio\nasync def process(envelope, ctx):\n    await asyncio.sleep(100)\n"
        )

        env = EventEnvelope(
            event="test.event",
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            description="test",
            visibility=EventVisibility.LOCAL,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        )
        req = request_to_dict(
            SandboxRequest(
                cartridge_name="slow_cart",
                envelope=env.to_stream_dict(),
                catalog_snapshot=[],
            )
        )

        with patch("teleclaude.events.sandbox.runner._CARTRIDGE_TIMEOUT", 0.05):
            resp = await _run_single_request(tmpdir, req)

        parsed = response_from_dict(resp)
        assert parsed.error == "timeout"


@pytest.mark.asyncio
async def test_handle_client_cartridge_exception_returns_error():
    """Runner returns an error response when cartridge raises a non-timeout exception."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from datetime import datetime

        from teleclaude.events.envelope import EventEnvelope

        Path(tmpdir, "boom_cart.py").write_text(
            "async def process(envelope, ctx):\n    raise ValueError('cartridge broke')\n"
        )

        env = EventEnvelope(
            event="test.event",
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            description="test",
            visibility=EventVisibility.LOCAL,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        )
        req = request_to_dict(
            SandboxRequest(
                cartridge_name="boom_cart",
                envelope=env.to_stream_dict(),
                catalog_snapshot=[],
            )
        )
        resp = await _run_single_request(tmpdir, req)
        parsed = response_from_dict(resp)
        assert parsed.error is not None
        assert parsed.envelope is None
        assert parsed.duration_ms > 0
