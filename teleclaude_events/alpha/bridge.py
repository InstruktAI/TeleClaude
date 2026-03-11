"""Alpha bridge cartridge — last cartridge in the approved system pipeline.

Routes events to alpha cartridges running inside the Docker sidecar.
All failures are caught and logged; the approved pipeline result is never blocked.
"""

from __future__ import annotations

import asyncio
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude_events.alpha.container import AlphaContainerManager, scan_cartridges
from teleclaude_events.alpha.protocol import AlphaRequest, FrameTooLargeError, read_frame, request_to_dict, response_from_dict, write_frame
from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

logger = get_logger(__name__)

_CARTRIDGE_TIMEOUT = 10.0  # seconds per cartridge call


class AlphaBridgeCartridge:
    name = "alpha-bridge"

    def __init__(self, manager: AlphaContainerManager) -> None:
        self._manager = manager

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        try:
            return await self._process(event, context)
        except Exception as exc:
            logger.error("Alpha bridge unexpected error: %s", exc, exc_info=True)
            return event

    async def _process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope:
        if (
            not self._manager.has_cartridges
            or self._manager.permanently_failed
            or self._manager.docker_unavailable
        ):
            return event

        cartridge_names = scan_cartridges(self._manager.cartridges_dir)
        if not cartridge_names:
            return event

        results: list[dict[str, Any]] = []

        # Build catalog snapshot from context
        catalog_snapshot = [
            schema.model_dump()
            for schema in (context.catalog.list_all() if context.catalog is not None else [])
        ]

        for name in cartridge_names:
            result_entry = await self._invoke_cartridge(name, event, catalog_snapshot)
            results.append(result_entry)

        event.payload["_alpha_results"] = results
        return event

    async def _invoke_cartridge(
        self,
        cartridge_name: str,
        event: EventEnvelope,
        catalog_snapshot: list[dict],
    ) -> dict[str, Any]:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._manager.socket_path),
                timeout=_CARTRIDGE_TIMEOUT,
            )
            try:
                request = AlphaRequest(
                    cartridge_name=cartridge_name,
                    envelope=event.to_stream_dict(),
                    catalog_snapshot=catalog_snapshot,
                )
                await write_frame(writer, request_to_dict(request))
                raw = await asyncio.wait_for(read_frame(reader), timeout=_CARTRIDGE_TIMEOUT)
                response = response_from_dict(raw)
                if response.error:
                    logger.warning("Alpha cartridge %r returned error: %s", cartridge_name, response.error)
                    return {"cartridge": cartridge_name, "error": response.error}
                return {"cartridge": cartridge_name, "result": response.envelope}
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        except asyncio.TimeoutError:
            logger.warning("Alpha cartridge %r timed out", cartridge_name)
            return {"cartridge": cartridge_name, "error": "timeout"}
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            logger.warning("Alpha cartridge %r connection error: %s", cartridge_name, exc)
            return {"cartridge": cartridge_name, "error": "unavailable"}
        except FrameTooLargeError as exc:
            logger.warning("Alpha cartridge %r frame too large: %s", cartridge_name, exc)
            return {"cartridge": cartridge_name, "error": "frame_too_large"}
        except Exception as exc:
            logger.warning("Alpha cartridge %r unexpected error: %s", cartridge_name, exc, exc_info=True)
            return {"cartridge": cartridge_name, "error": str(exc)}
