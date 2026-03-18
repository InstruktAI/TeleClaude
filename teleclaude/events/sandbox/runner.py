"""Sandbox runner — Unix socket server running inside the Docker sidecar.

Listens for SandboxRequest frames, loads and executes the addressed cartridge,
and returns an SandboxResponse frame. Each request reloads the cartridge from disk
(hot-reload, no module cache).
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
import types
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict
from teleclaude.events.catalog import EventCatalog, EventSchema
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.sandbox.protocol import (
    FrameTooLargeError,
    SandboxResponse,
    read_frame,
    request_from_dict,
    response_to_dict,
    write_frame,
)

logger = get_logger(__name__)

_CARTRIDGE_TIMEOUT = 10.0  # seconds


def _build_catalog_from_snapshot(snapshot: list[JsonDict]) -> EventCatalog:
    """Rebuild a minimal EventCatalog from a serialized snapshot (no DB required)."""
    catalog = EventCatalog()
    for item in snapshot:
        try:
            schema = EventSchema(**item)  # type: ignore[arg-type]
            catalog.register(schema)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Skipping catalog snapshot entry: %s", e)
    return catalog


def _load_cartridge_module(cartridges_dir: str, cartridge_name: str) -> types.ModuleType:
    """Load a cartridge from disk into a fresh module object (no cache)."""
    path = Path(cartridges_dir) / f"{cartridge_name}.py"
    if not path.exists():
        raise FileNotFoundError(f"Cartridge not found: {path}")
    spec = importlib.util.spec_from_file_location(f"sandbox_cartridge_{cartridge_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for: {path}")
    module = types.ModuleType(spec.name)
    spec.loader.exec_module(module)
    return module


def _load_process_callable(
    cartridges_dir: str,
    cartridge_name: str,
) -> Callable[[EventEnvelope, PipelineContext], Awaitable[EventEnvelope | None]]:
    """Load and return the `process` callable for one sandbox cartridge module."""
    module = _load_cartridge_module(cartridges_dir, cartridge_name)
    process = getattr(module, "process", None)
    if not callable(process):
        raise AttributeError(f"Cartridge {cartridge_name!r} has no callable 'process'")
    return cast(Callable[[EventEnvelope, PipelineContext], Awaitable[EventEnvelope | None]], process)


async def _run_process_callable(
    process_callable: Callable[[EventEnvelope, PipelineContext], Awaitable[EventEnvelope | None]],
    envelope: EventEnvelope,
    context: PipelineContext,
) -> EventEnvelope | None:
    """Execute a loaded process callable with the provided pipeline context."""
    return await process_callable(envelope, context)


class SandboxRunner:
    """Run a Unix-socket server that executes sandbox cartridges in-process."""

    def __init__(self, socket_path: str, cartridges_dir: str) -> None:
        self._socket_path = socket_path
        self._cartridges_dir = cartridges_dir

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Serve sandbox cartridge requests until the shutdown event is set."""
        server = await asyncio.start_unix_server(self._handle_client, path=self._socket_path)
        logger.info("SandboxRunner listening on %s", self._socket_path)
        async with server:
            await shutdown_event.wait()
        logger.info("SandboxRunner shutting down")

    def socket_path(self) -> str:
        """Return the Unix-socket path served by this runner."""
        return self._socket_path

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read one request frame, execute it, and write back one response frame."""
        try:
            raw = await read_frame(reader)
            request = request_from_dict(raw)

            # Ping handler — health check, no disk access
            if request.cartridge_name == "__ping__":
                await write_frame(writer, response_to_dict(SandboxResponse(envelope=None, error=None, duration_ms=0.0)))
                return

            start = time.monotonic()
            try:
                process_callable = _load_process_callable(self._cartridges_dir, request.cartridge_name)
                envelope = EventEnvelope.from_stream_dict(request.envelope)  # type: ignore[arg-type]
                catalog = _build_catalog_from_snapshot(request.catalog_snapshot)
                context = PipelineContext(catalog=catalog, db=None)

                result: EventEnvelope | None = await asyncio.wait_for(
                    _run_process_callable(process_callable, envelope, context),
                    timeout=_CARTRIDGE_TIMEOUT,
                )
                duration_ms = (time.monotonic() - start) * 1000
                result_dict = result.to_stream_dict() if result is not None else None
                response = SandboxResponse(
                    envelope=result_dict,
                    error=None,
                    duration_ms=duration_ms,
                )
            except TimeoutError:
                duration_ms = (time.monotonic() - start) * 1000
                logger.warning("Cartridge %r timed out after %.0fms", request.cartridge_name, duration_ms)
                response = SandboxResponse(envelope=None, error="timeout", duration_ms=duration_ms)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                duration_ms = (time.monotonic() - start) * 1000
                logger.exception("Cartridge %r raised: %s", request.cartridge_name, exc)
                response = SandboxResponse(envelope=None, error=str(exc), duration_ms=duration_ms)

            await write_frame(writer, response_to_dict(response))
        except FrameTooLargeError as exc:
            logger.warning("Frame too large, dropping: %s", exc)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Unexpected error handling sandbox client: %s", exc, exc_info=True)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
