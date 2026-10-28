"""The ingress's webhook receiver as a process of its own beside the daemon (ADR-0148).

It serves the inbound endpoints on the loopback port the reverse proxy forwards to, verifies each request,
and relays it onto the cluster stream through the claim that publishes each delivery once. It carries
nothing of the daemon, so it keeps receiving while the daemon restarts or an install replaces it.

Run as ``python -m teleclaude.hooks.ingress_receiver`` under its own service unit.
"""

from __future__ import annotations

import asyncio
from typing import Final

import uvicorn
from fastapi import FastAPI
from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.events.envelope_facts import EnvelopeFactResolver
from teleclaude.events.producer import EventProducer
from teleclaude.events.scoped_redis import close_scoped_clients, scoped_redis_clients
from teleclaude.hooks.inbound import install_inbound_routes
from teleclaude.logging_config import setup_logging
from teleclaude.services.project_catalog.ownership import load_project_ownership_index

logger = get_logger(__name__)

_HOST: Final = "127.0.0.1"
_UVICORN_LOG_LEVEL: Final = "warning"
_APP_TITLE: Final = "TeleClaude ingress receiver"
_LOG_SOURCE: Final = "ingress-receiver"
_NOT_INGRESS_EVENT: Final = "ingress_receiver_not_ingress_node"
_LISTENING_EVENT: Final = "ingress_receiver_listening"


def build_receiver_app(producer: EventProducer) -> FastAPI:
    """The receiver's application: the inbound endpoints and nothing else."""
    app = FastAPI(title=_APP_TITLE)
    install_inbound_routes(app, producer)
    return app


async def serve() -> None:
    """Serve the inbound endpoints until the process is stopped."""
    if not config.computer.is_ingress_node:
        # The unit is deployed on the ingress computer only; elsewhere there is nothing to receive.
        logger.warning(_NOT_INGRESS_EVENT)
        return
    clients = scoped_redis_clients()
    producer = EventProducer(
        redis_clients=clients,
        fact_resolver=EnvelopeFactResolver(session_id=lambda: None, ownership_index=load_project_ownership_index),
    )
    server = uvicorn.Server(
        uvicorn.Config(
            build_receiver_app(producer),
            host=_HOST,
            port=config.api.tcp_port,
            log_level=_UVICORN_LOG_LEVEL,
        )
    )
    logger.info(_LISTENING_EVENT, host=_HOST, port=config.api.tcp_port)
    try:
        await server.serve()
    finally:
        await close_scoped_clients(clients)


def main() -> None:
    """Entry point of the receiver's service unit."""
    setup_logging(level=config.daemon.log_level, source=_LOG_SOURCE)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
