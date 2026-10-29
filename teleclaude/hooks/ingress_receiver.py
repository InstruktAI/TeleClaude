"""The ingress's webhook receiver as a process of its own beside the daemon (ADR-0148).

It serves the inbound endpoints on the loopback port the reverse proxy forwards to, verifies each request,
and relays it onto the cluster stream through the claim that publishes each delivery once. It carries
nothing of the daemon, so it keeps receiving while the daemon restarts or an install replaces it.

Its systemd socket unit holds the listening socket and hands it over, so connections arriving while the
receiver restarts wait in the socket's queue. Run outside a unit, it binds the port itself.

Run as ``python -m teleclaude.hooks.ingress_receiver`` under its own service unit.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from typing import Final

import uvicorn
from fastapi import FastAPI
from instrukt_ai_logging import get_logger

from teleclaude.config.declaration_changes import identity_declaration_watch_paths
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.machine import (
    config,
    config_path,
    machine_configuration_sources,
    reload_config,
    restart_required_sections,
)
from teleclaude.core.config_validation_reports import MACHINE_CONFIGURATION, ConfigValidationReports
from teleclaude.core.config_watcher import ConfigWatcher
from teleclaude.core.reconciliation.installation import loaded_release_revision, runs_active_release
from teleclaude.events.envelope_facts import EnvelopeFactResolver
from teleclaude.events.processor import ensure_consumer_group
from teleclaude.events.producer import EventProducer, configure_producer
from teleclaude.events.scope import EventScope
from teleclaude.events.scoped_redis import close_scoped_clients, scoped_redis_clients
from teleclaude.hooks.inbound import install_inbound_routes
from teleclaude.hooks.relay_delivery import relay_delivery_group
from teleclaude.logging_config import setup_logging
from teleclaude.services.project_catalog.ownership import load_project_ownership_index
from teleclaude.services.project_catalog.service import get_project_catalog_service

logger = get_logger(__name__)

# systemd hands the first activated socket over as this descriptor (sd_listen_fds).
_SYSTEMD_FIRST_FD: Final = 3
_STARTUP_POLL_S: Final = 0.05
# How often the receiver checks whether an install moved the active-release pointer.
_RELEASE_POLL_S: Final = 2.0
# The exit status that asks the unit to start the receiver again (EX_TEMPFAIL): the release or a section of the
# machine configuration that needs a restart changed. A clean exit (0) is not restarted by the unit; on a computer
# that is not the ingress, a connection to the held socket can still start the receiver, which exits before serving.
_RESTART_STATUS: Final = 75


def build_receiver_app(producer: EventProducer) -> FastAPI:
    """The receiver's application: the inbound endpoints and nothing else."""
    app = FastAPI(title="TeleClaude ingress receiver")
    install_inbound_routes(app, producer)
    return app


def _systemd_socket() -> socket.socket | None:
    """The socket systemd activated for this process, if it was started that way."""
    listen_pid = os.environ.get("LISTEN_PID")  # guard: direct-env-read - allowed: systemd socket activation
    listen_fds = os.environ.get("LISTEN_FDS", "0")  # guard: direct-env-read - allowed: systemd socket activation
    if listen_pid != str(os.getpid()) or int(listen_fds) < 1:
        return None
    return socket.socket(fileno=_SYSTEMD_FIRST_FD)


def _listening_socket() -> tuple[socket.socket, bool]:
    """The socket to serve on, and whether the service manager handed it over."""
    held = _systemd_socket()
    if held is not None:
        return held, True
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bound.bind(("127.0.0.1", config.api.tcp_port))
    return bound, False


async def _refresh_catalog() -> None:
    """Reload the project catalog after a registry or declaration change, as the daemon's watchers do."""
    get_project_catalog_service().refresh()


class _Receiver:
    """One receiver process: serves until stopped, and says whether its unit should start it again."""

    def __init__(self, server: uvicorn.Server, reports: ConfigValidationReports) -> None:
        self._server = server
        self._reports = reports
        self.restart = False

    def stop(self, *, restart: bool) -> None:
        self.restart = self.restart or restart
        self._server.should_exit = True

    def supervise(self, task: asyncio.Task[None], event: str) -> None:
        """Stop serving, for a fresh process, when a task the receiver depends on ends unexpectedly."""

        def ended(done: asyncio.Task[None]) -> None:
            # A task that finishes on its own has already stopped the receiver for its reason.
            if done.cancelled() or done.exception() is None:
                return
            logger.error(event, exc_info=done.exception())
            self.stop(restart=True)

        task.add_done_callback(ended)

    async def follow_release(self) -> None:
        """Stop serving once the active release is no longer this process's, so the unit starts the new one."""
        while runs_active_release():
            await asyncio.sleep(_RELEASE_POLL_S)
        logger.info("ingress_receiver_release_moved")
        self.stop(restart=True)

    async def machine_configuration_changed(self) -> None:
        """Apply a validated machine configuration change as the daemon does; an invalid one changes nothing."""
        try:
            changed = reload_config()
        except ConfigLoadError as error:
            # The running configuration stays in force, as for the daemon (machine-config-load).
            await self._reports.refused(MACHINE_CONFIGURATION, config_path, error)
            return
        await self._reports.accepted(MACHINE_CONFIGURATION, config_path)
        if not config.computer.is_ingress_node:
            logger.info("ingress_receiver_no_longer_ingress")
            self.stop(restart=False)
            return
        restart = restart_required_sections(changed)
        if restart:
            logger.info("ingress_receiver_configuration_changed", sections=sorted(restart))
            self.stop(restart=True)


async def serve() -> int:
    """Serve the inbound endpoints until the process is stopped; return the process's exit status."""
    # The machine watcher takes its baseline before the role is read, so a change written meanwhile is seen.
    pending: list[_Receiver] = []

    async def machine_changed() -> None:
        if pending:
            await pending[0].machine_configuration_changed()

    machine = ConfigWatcher(machine_configuration_sources(), machine_changed)
    reports = ConfigValidationReports()
    startup_refusal: ConfigLoadError | None = None
    try:
        reload_config()
    except ConfigLoadError as error:
        # Startup keeps the configuration it loaded; the refusal is reported once events can be published.
        startup_refusal = error
    if not config.computer.is_ingress_node:
        # Not the ingress: exit before serving; the next install or start removes this computer's receiver units.
        logger.warning("ingress_receiver_not_ingress_node")
        if startup_refusal is not None:
            await reports.refused(MACHINE_CONFIGURATION, config_path, startup_refusal)
        return 0
    clients = scoped_redis_clients()
    producer = EventProducer(
        redis_clients=clients,
        fact_resolver=EnvelopeFactResolver(session_id=lambda: None, ownership_index=load_project_ownership_index),
    )
    # Platform events this process reports (configuration refusals) go through its producer.
    configure_producer(producer)
    if startup_refusal is not None:
        await reports.refused(MACHINE_CONFIGURATION, config_path, startup_refusal)
    tasks: list[asyncio.Task[None]] = []
    try:
        # This computer's relay group exists before the first relay, so its daemon reads every event relayed here.
        await ensure_consumer_group(
            clients.for_scope(EventScope.CLUSTER), producer.stream_name(), relay_delivery_group(config.computer.name)
        )
        listener, handed_over = _listening_socket()
        server = uvicorn.Server(uvicorn.Config(build_receiver_app(producer), log_level="warning"))
        receiver = _Receiver(server, reports)
        pending.append(receiver)
        # Ownership facts on relayed events come from the catalog, which this process keeps current itself.
        declarations = asyncio.create_task(ConfigWatcher(identity_declaration_watch_paths, _refresh_catalog).run())
        receiver.supervise(declarations, "ingress_receiver_declaration_watcher_ended")
        tasks += [declarations, asyncio.create_task(machine.run())]
        receiver.supervise(tasks[-1], "ingress_receiver_configuration_watcher_ended")
        # A receiver started from a release follows the pointer; one started from a checkout has none to follow.
        if loaded_release_revision() is not None:
            tasks.append(asyncio.create_task(receiver.follow_release()))
            receiver.supervise(tasks[-1], "ingress_receiver_release_follower_ended")
        serve_task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started and not serve_task.done():
            await asyncio.sleep(_STARTUP_POLL_S)
        if server.started:
            logger.info("ingress_receiver_listening", address=listener.getsockname(), handed_over=handed_over)
        await serve_task
        return _RESTART_STATUS if receiver.restart else 0
    except Exception:
        logger.exception("ingress_receiver_failed")
        raise
    finally:
        for task in tasks:
            task.cancel()
        await close_scoped_clients(clients)


def main() -> None:
    """Entry point of the receiver's service unit."""
    setup_logging(level=config.daemon.log_level, source="ingress-receiver")
    sys.exit(asyncio.run(serve()))


if __name__ == "__main__":
    main()
