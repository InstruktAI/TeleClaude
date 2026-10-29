"""Serve webhook ingress through the API app on the loopback interface."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from typing import Final

import uvicorn
from fastapi import FastAPI
from instrukt_ai_logging import get_logger

from teleclaude.api.ws_constants import API_WS_PING_INTERVAL_S, API_WS_PING_TIMEOUT_S
from teleclaude.core.cleanup_step import cleanup_step

logger = get_logger(__name__)

_API_TCP_HOST: Final = "127.0.0.1"
_UVICORN_LOG_LEVEL: Final = "warning"
_TASK_NAME: Final = "webhook-ingress-listener"
_PORT_PROBE_ATTEMPTS: Final = 20
_PORT_PROBE_INTERVAL_S: Final = 0.1
_SERVER_START_ATTEMPTS: Final = 50
_SERVER_START_INTERVAL_S: Final = 0.1

_ALREADY_RUNNING = "Webhook ingress listener already running; skipping start"
_PORT_UNAVAILABLE = "Webhook ingress listener could not bind to %s:%d after retries"
_START_EXITED = "Webhook ingress listener exited during startup on %s:%d"
_START_CANCELLED = "Webhook ingress listener startup was cancelled on %s:%d"
_START_TIMEOUT = "Webhook ingress listener failed to start on %s:%d within timeout"
_LISTENING = "Webhook ingress listener listening on %s:%d"
_TASK_CRASHED = "Webhook ingress listener task crashed on %s:%d"
_TASK_EXITED = "Webhook ingress listener task exited unexpectedly on %s:%d"
_STOP_TIMEOUT = "Timed out stopping webhook ingress listener; cancelling task"
_NO_EXCEPTION_TYPE = "NoException"
_INGRESS_STOP_CLEANUP_COMPONENT = "webhook_ingress_listener"


class WebhookIngressListener:
    """Manage the loopback Uvicorn server that shares the daemon API app."""

    def __init__(
        self,
        app: FastAPI,
        port: int,
        keep_alive_timeout_s: int,
        stop_timeout_s: float,
        on_unexpected_exit: Callable[[BaseException | None, bool | None], None],
    ) -> None:
        self._app = app
        self._port = port
        self._keep_alive_timeout_s = keep_alive_timeout_s
        self._stop_timeout_s = stop_timeout_s
        self._on_unexpected_exit = on_unexpected_exit
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[object] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the listener after confirming the loopback port can bind."""
        if self._server_task and not self._server_task.done():
            logger.warning(_ALREADY_RUNNING)
            return

        if not await self._port_is_available():
            logger.error(_PORT_UNAVAILABLE, _API_TCP_HOST, self._port, host=_API_TCP_HOST, port=self._port)
            return

        server_config = uvicorn.Config(
            self._app,
            host=_API_TCP_HOST,
            port=self._port,
            log_level=_UVICORN_LOG_LEVEL,
            ws_ping_interval=API_WS_PING_INTERVAL_S,
            ws_ping_timeout=API_WS_PING_TIMEOUT_S,
            timeout_keep_alive=self._keep_alive_timeout_s,
        )
        self._server = uvicorn.Server(server_config)
        server = self._server
        self._running = True

        serve_coro = server._serve() if hasattr(server, "_serve") else server.serve()
        self._server_task = asyncio.create_task(serve_coro, name=_TASK_NAME)
        self._server_task.add_done_callback(lambda task, current=server: self._on_server_task_done(task, current))

        for _ in range(_SERVER_START_ATTEMPTS):
            if server.started:
                break
            if self._server_task.done():
                try:
                    error = self._server_task.exception()
                except asyncio.CancelledError:
                    self._running = False
                    logger.error(_START_CANCELLED, _API_TCP_HOST, self._port, host=_API_TCP_HOST, port=self._port)
                    return
                error_type = type(error).__name__ if error else _NO_EXCEPTION_TYPE
                self._running = False
                logger.error(
                    _START_EXITED,
                    _API_TCP_HOST,
                    self._port,
                    host=_API_TCP_HOST,
                    port=self._port,
                    error_type=error_type,
                    error=error,
                )
                return
            await asyncio.sleep(_SERVER_START_INTERVAL_S)

        if server.started:
            logger.info(_LISTENING, _API_TCP_HOST, self._port, host=_API_TCP_HOST, port=self._port)
            return

        logger.error(_START_TIMEOUT, _API_TCP_HOST, self._port, host=_API_TCP_HOST, port=self._port)
        await self.stop()

    async def stop(self) -> None:
        """Stop the loopback server and its task before the Unix API server."""
        self._running = False
        server = self._server
        task = self._server_task
        if server:
            if server.started:
                server.should_exit = True
            elif task:
                task.cancel()

        if not task:
            return

        with cleanup_step(_INGRESS_STOP_CLEANUP_COMPONENT):
            try:
                await asyncio.wait_for(task, timeout=self._stop_timeout_s)
            except TimeoutError:
                logger.warning(_STOP_TIMEOUT)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

    async def _port_is_available(self) -> bool:
        for _ in range(_PORT_PROBE_ATTEMPTS):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind((_API_TCP_HOST, self._port))
            except OSError:
                await asyncio.sleep(_PORT_PROBE_INTERVAL_S)
            else:
                return True
        return False

    def _on_server_task_done(self, task: asyncio.Task[object], server: uvicorn.Server) -> None:
        if not self._running:
            return

        try:
            error = task.exception()
        except asyncio.CancelledError:
            return

        if error:
            logger.error(
                _TASK_CRASHED,
                _API_TCP_HOST,
                self._port,
                host=_API_TCP_HOST,
                port=self._port,
                error_type=type(error).__name__,
                error=error,
            )
        elif not server.should_exit:
            logger.error(_TASK_EXITED, _API_TCP_HOST, self._port, host=_API_TCP_HOST, port=self._port)
        else:
            return

        # A listener that never finished starting is a startup failure, which the start path owns.
        if server.started:
            self._on_unexpected_exit(error, server.should_exit)
