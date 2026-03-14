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
from pathlib import Path

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
            schema = EventSchema(**item)
            catalog.register(schema)
        except Exception as e:
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
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class SandboxRunner:
    def __init__(self, socket_path: str, cartridges_dir: str) -> None:
        self._socket_path = socket_path
        self._cartridges_dir = cartridges_dir

    async def start(self, shutdown_event: asyncio.Event) -> None:
        server = await asyncio.start_unix_server(self._handle_client, path=self._socket_path)
        logger.info("SandboxRunner listening on %s", self._socket_path)
        async with server:
            await shutdown_event.wait()
        logger.info("SandboxRunner shutting down")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await read_frame(reader)
            request = request_from_dict(raw)

            # Ping handler — health check, no disk access
            if request.cartridge_name == "__ping__":
                await write_frame(writer, response_to_dict(SandboxResponse(envelope=None, error=None, duration_ms=0.0)))
                return

            start = time.monotonic()
            try:
                module = _load_cartridge_module(self._cartridges_dir, request.cartridge_name)
                process_fn = getattr(module, "process", None)
                if not callable(process_fn):
                    raise AttributeError(f"Cartridge {request.cartridge_name!r} has no callable 'process'")

                envelope = EventEnvelope.from_stream_dict(request.envelope)
                catalog = _build_catalog_from_snapshot(request.catalog_snapshot)
                context = PipelineContext(catalog=catalog, db=None)  # type: ignore[arg-type]

                result: EventEnvelope | None = await asyncio.wait_for(
                    process_fn(envelope, context), timeout=_CARTRIDGE_TIMEOUT
                )
                duration_ms = (time.monotonic() - start) * 1000
                result_dict = result.to_stream_dict() if result is not None else None
                response = SandboxResponse(envelope=result_dict, error=None, duration_ms=duration_ms)
            except TimeoutError:
                duration_ms = (time.monotonic() - start) * 1000
                logger.warning("Cartridge %r timed out after %.0fms", request.cartridge_name, duration_ms)
                response = SandboxResponse(envelope=None, error="timeout", duration_ms=duration_ms)
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                logger.exception("Cartridge %r raised: %s", request.cartridge_name, exc)
                response = SandboxResponse(envelope=None, error=str(exc), duration_ms=duration_ms)

            await write_frame(writer, response_to_dict(response))
        except FrameTooLargeError as exc:
            logger.warning("Frame too large, dropping: %s", exc)
        except Exception as exc:
            logger.error("Unexpected error handling sandbox client: %s", exc, exc_info=True)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
