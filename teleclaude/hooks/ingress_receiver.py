"""The ingress's webhook receiver as a process of its own beside the daemon (ADR-0148).

It serves the inbound endpoints on the loopback port the reverse proxy forwards to, verifies each request,
and relays it onto the cluster stream through the claim that publishes each delivery once. It carries
nothing of the daemon, so it keeps receiving while the daemon restarts or an install replaces it.

Its service unit holds the listening socket and hands it over (a systemd socket unit, a launchd socket
declaration), so connections arriving while the receiver restarts wait in the socket's queue. Run outside
a unit, it binds the port itself.

Run as ``python -m teleclaude.hooks.ingress_receiver`` under its own service unit.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import socket
import sys
from typing import Final

import uvicorn
from fastapi import FastAPI
from instrukt_ai_logging import get_logger

from teleclaude.config.declaration_changes import identity_declaration_watch_paths
from teleclaude.config.machine import config
from teleclaude.core.config_watcher import ConfigWatcher
from teleclaude.core.reconciliation.installation import loaded_release_revision, runs_active_release
from teleclaude.events.envelope_facts import EnvelopeFactResolver
from teleclaude.events.producer import EventProducer
from teleclaude.events.scoped_redis import close_scoped_clients, scoped_redis_clients
from teleclaude.hooks.inbound import install_inbound_routes
from teleclaude.logging_config import setup_logging
from teleclaude.services.project_catalog.ownership import load_project_ownership_index
from teleclaude.services.project_catalog.service import get_project_catalog_service

logger = get_logger(__name__)

_HOST: Final = "127.0.0.1"
# The name the launchd definition gives the socket it holds for the receiver.
LAUNCHD_SOCKET_NAME: Final = "Listeners"
# systemd hands the first activated socket over as this descriptor (sd_listen_fds).
_SYSTEMD_FIRST_FD: Final = 3
_STARTUP_POLL_S: Final = 0.05
# How often the receiver checks whether an install moved the active-release pointer.
_RELEASE_POLL_S: Final = 2.0


def build_receiver_app(producer: EventProducer) -> FastAPI:
    """The receiver's application: the inbound endpoints and nothing else."""
    app = FastAPI(title="TeleClaude ingress receiver")
    install_inbound_routes(app, producer)
    return app


def _systemd_socket() -> socket.socket | None:
    """The socket systemd activated for this process, if it was started that way."""
    listen_pid = os.environ.get("LISTEN_PID")  # guard: direct-env-read - allowed: systemd socket-activation protocol
    listen_fds = os.environ.get(
        "LISTEN_FDS", "0"
    )  # guard: direct-env-read - allowed: systemd socket-activation protocol
    if listen_pid != str(os.getpid()) or int(listen_fds) < 1:
        return None
    return socket.socket(fileno=_SYSTEMD_FIRST_FD)


def _launchd_socket() -> socket.socket | None:
    """The socket launchd holds for this process under ``LAUNCHD_SOCKET_NAME``, if it declares one."""
    if sys.platform != "darwin":
        return None
    libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    fds = ctypes.POINTER(ctypes.c_int)()
    count = ctypes.c_size_t(0)
    status = libsystem.launch_activate_socket(LAUNCHD_SOCKET_NAME.encode(), ctypes.byref(fds), ctypes.byref(count))
    if status != 0 or count.value < 1:
        # ESRCH: not started by launchd with this socket; ENOENT: no such socket declared.
        return None
    descriptors = [fds[index] for index in range(count.value)]
    libsystem.free(fds)
    return socket.socket(fileno=descriptors[0])


def _listening_socket() -> tuple[socket.socket, bool]:
    """The socket to serve on, and whether the service manager handed it over."""
    held = _systemd_socket() or _launchd_socket()
    if held is not None:
        return held, True
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bound.bind((_HOST, config.api.tcp_port))
    return bound, False


async def _refresh_catalog() -> None:
    """Reload the project catalog after a registry or declaration change, as the daemon's watchers do."""
    get_project_catalog_service().refresh()


async def _exit_when_release_moves(server: uvicorn.Server) -> None:
    """Stop serving once the active release is no longer this process's, so the unit starts the new one."""
    while runs_active_release():
        await asyncio.sleep(_RELEASE_POLL_S)
    logger.info("ingress_receiver_release_moved")
    server.should_exit = True


async def serve() -> None:
    """Serve the inbound endpoints until the process is stopped."""
    if not config.computer.is_ingress_node:
        # The unit is deployed on the ingress computer only; elsewhere there is nothing to receive.
        logger.warning("ingress_receiver_not_ingress_node")
        return
    clients = scoped_redis_clients()
    producer = EventProducer(
        redis_clients=clients,
        fact_resolver=EnvelopeFactResolver(session_id=lambda: None, ownership_index=load_project_ownership_index),
    )
    # Ownership facts on relayed events come from the catalog, which this process keeps current itself.
    watcher_task = asyncio.create_task(ConfigWatcher(identity_declaration_watch_paths, _refresh_catalog).run())
    listener, handed_over = _listening_socket()
    server = uvicorn.Server(uvicorn.Config(build_receiver_app(producer), log_level="warning"))
    serve_task = asyncio.create_task(server.serve(sockets=[listener]))
    # A receiver started from a release follows the pointer; one started from a checkout has none to follow.
    release_task = (
        asyncio.create_task(_exit_when_release_moves(server)) if loaded_release_revision() is not None else None
    )
    try:
        while not server.started and not serve_task.done():
            await asyncio.sleep(_STARTUP_POLL_S)
        if server.started:
            logger.info("ingress_receiver_listening", address=listener.getsockname(), handed_over=handed_over)
        await serve_task
    finally:
        watcher_task.cancel()
        if release_task is not None:
            release_task.cancel()
        await close_scoped_clients(clients)


def main() -> None:
    """Entry point of the receiver's service unit."""
    setup_logging(level=config.daemon.log_level, source="ingress-receiver")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
