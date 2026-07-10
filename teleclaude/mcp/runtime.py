"""Daemon-owned lazy MCP lease runtime."""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

from dotenv import dotenv_values
from instrukt_ai_logging import get_logger

from teleclaude.mcp.protocol import JsonObject, McpProtocolError, StdioMcpClient, ToolCatalog
from teleclaude.mcp.registry import (
    McpConcurrency,
    McpRegistry,
    McpServerConfig,
    McpTransport,
    RegistryError,
    extract_env_names_from_text,
    load_effective_registry,
    remote_proxy_command,
)
from teleclaude.paths import ENV_PATH

logger = get_logger(__name__)

_ENV_REFERENCE_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:[:?+\-=][^}]*)?\}|([A-Za-z_][A-Za-z0-9_]*))")


class McpRuntimeError(RuntimeError):
    """Caller-safe MCP runtime failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "mcp_runtime_error",
        slug: str | None = None,
        missing_env: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.slug = slug
        self.missing_env = missing_env

    def to_error_dict(self) -> JsonObject:
        """Return a caller-safe error object."""
        data: JsonObject = {"code": self.code, "message": self.message}
        if self.slug is not None:
            data["server"] = self.slug
        if self.missing_env:
            data["missingEnv"] = list(self.missing_env)
        return data


@dataclass
class _Lease:
    server: McpServerConfig
    fingerprint: str
    client: StdioMcpClient
    lock: _AsyncLock
    tools: ToolCatalog | None
    idle_deadline: float


class McpRuntime:
    """Own MCP server leases and expose lazy list/call operations."""

    def __init__(
        self,
        *,
        repo_root: Path,
        env_path: Path = ENV_PATH,
        registry: McpRegistry | None = None,
        clock: _Clock | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._env_path = env_path
        self._registry = registry
        self._clock = clock
        self._leases: dict[str, _Lease] = {}
        self._lease_lock = asyncio.Lock()

    def list_servers(self, *, exclude: set[str] | None = None) -> list[JsonObject]:
        """Return the configured server catalog without starting leases."""
        return [server.to_catalog_dict() for server in self._load_registry().enabled_servers(exclude=exclude)]

    async def list_tools(self, slug: str) -> JsonObject:
        """Return a server's tool catalog, initializing only that server."""
        lease = await self._lease_for(slug)
        async with lease.lock:
            try:
                if lease.tools is None or lease.client.tool_list_changed:
                    lease.tools = await asyncio.wait_for(
                        lease.client.list_tools(), timeout=lease.server.tool_timeout_seconds
                    )
            except TimeoutError as exc:
                await self._close_lease(slug)
                raise McpRuntimeError("MCP tools/list timed out", code="tool_timeout", slug=slug) from exc
            except _CALLER_SAFE_PROTOCOL_FAILURES as exc:
                raise McpRuntimeError("MCP tools/list failed", code="tool_list_failed", slug=slug) from exc
            self._refresh_deadline(lease)
            return {"server": slug, "tools": lease.tools.tools}

    async def call_tool(self, slug: str, tool_name: str, arguments: JsonObject) -> JsonObject:
        """Call one tool through the selected server lease."""
        lease = await self._lease_for(slug)
        async with lease.lock:
            try:
                result = await asyncio.wait_for(
                    lease.client.call_tool(tool_name, arguments),
                    timeout=lease.server.tool_timeout_seconds,
                )
            except TimeoutError as exc:
                await self._close_lease(slug)
                raise McpRuntimeError("MCP tool call timed out", code="tool_timeout", slug=slug) from exc
            except _CALLER_SAFE_PROTOCOL_FAILURES as exc:
                raise McpRuntimeError("MCP tool call failed", code="tool_call_failed", slug=slug) from exc
            self._refresh_deadline(lease)
            return {"server": slug, "tool": tool_name, "result": result}

    async def reap_idle(self) -> None:
        """Close leases whose idle deadlines have passed."""
        now = self._now()
        expired = [slug for slug, lease in self._leases.items() if lease.idle_deadline <= now]
        for slug in expired:
            await self._close_lease(slug)

    async def close(self) -> None:
        """Close all active MCP leases."""
        for slug in list(self._leases):
            await self._close_lease(slug)

    def active_lease_slugs(self) -> list[str]:
        """Return active lease slugs for diagnostics and tests."""
        return sorted(self._leases)

    async def _lease_for(self, slug: str) -> _Lease:
        async with self._lease_lock:
            registry = self._load_registry()
            try:
                server = registry.require_server(slug)
            except RegistryError as exc:
                raise McpRuntimeError(str(exc), code="unknown_server", slug=slug) from exc
            env_values = self._load_env_values()
            missing = tuple(name for name in server.env_references if name not in env_values)
            if missing:
                raise McpRuntimeError(
                    "MCP server is missing required environment values",
                    code="missing_env",
                    slug=slug,
                    missing_env=missing,
                )
            fingerprint = server.fingerprint(env_values)
            existing = self._leases.get(slug)
            if existing is not None and existing.fingerprint == fingerprint:
                self._refresh_deadline(existing)
                return existing
            if existing is not None:
                await self._close_lease(slug)
            client = await self._start_client(server, env_values)
            lease = _Lease(
                server=server,
                fingerprint=fingerprint,
                client=client,
                lock=asyncio.Lock() if server.concurrency == McpConcurrency.SERIALIZED else _NullAsyncLock(),
                tools=None,
                idle_deadline=self._now() + server.idle_ttl_seconds,
            )
            self._leases[slug] = lease
            return lease

    async def _start_client(self, server: McpServerConfig, env_values: dict[str, str]) -> StdioMcpClient:
        process: asyncio.subprocess.Process | None = None
        client: StdioMcpClient | None = None
        try:
            command, args = _launch_command(server)
            resolved_args = [_resolve_placeholders(arg, env_values) for arg in args]
            resolved_command = _resolve_placeholders(command, env_values)
            child_env = _build_child_env(server, env_values)
            # MCP servers are external tools; there is no Python API for their stdio JSON-RPC process boundary.
            process = await asyncio.create_subprocess_exec(
                resolved_command,
                *resolved_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=child_env,
            )
            client = StdioMcpClient(process)
            await asyncio.wait_for(client.start(), timeout=server.startup_timeout_seconds)
            return client
        except asyncio.CancelledError:
            if client is not None:
                await client.close()
            elif process is not None:
                await _terminate_process(process)
            raise
        except (OSError, TimeoutError, RegistryError, McpProtocolError, BrokenPipeError, ConnectionError) as exc:
            if client is not None:
                await client.close()
            elif process is not None:
                await _terminate_process(process)
            logger.warning("MCP server startup failed", server=server.slug, error_type=type(exc).__name__)
            raise McpRuntimeError("MCP server failed to start", code="startup_failed", slug=server.slug) from exc

    def _load_registry(self) -> McpRegistry:
        return self._registry or load_effective_registry(self._repo_root)

    def _load_env_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if self._env_path.exists():
            for key, value in dotenv_values(self._env_path).items():
                if isinstance(value, str) and value:
                    values[key] = value
        return values

    def _refresh_deadline(self, lease: _Lease) -> None:
        lease.idle_deadline = self._now() + lease.server.idle_ttl_seconds

    async def _close_lease(self, slug: str) -> None:
        lease = self._leases.pop(slug, None)
        if lease is None:
            return
        await lease.client.close()

    def _now(self) -> float:
        if self._clock is not None and hasattr(self._clock, "now"):
            return float(self._clock.now())
        return time.monotonic()


class _Clock(Protocol):
    def now(self) -> float:
        """Return monotonic test/runtime time."""
        ...


class _AsyncLock(Protocol):
    async def __aenter__(self) -> object:
        """Enter the async lock."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object:
        """Exit the async lock."""


class _NullAsyncLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


_CALLER_SAFE_PROTOCOL_FAILURES = (McpProtocolError, BrokenPipeError, ConnectionError, OSError)
_PROCESS_ENV_ALLOWLIST = frozenset(
    {"HOME", "LANG", "LC_ALL", "LOGNAME", "PATH", "SHELL", "TEMP", "TMP", "TMPDIR", "USER"}
)


def _launch_command(server: McpServerConfig) -> tuple[str, list[str]]:
    if server.transport == McpTransport.STDIO:
        if server.command is None:
            raise McpRuntimeError("MCP stdio server is missing command", code="invalid_server", slug=server.slug)
        return server.command, list(server.args)
    return remote_proxy_command(server)


def _build_child_env(server: McpServerConfig, env_values: dict[str, str]) -> dict[str, str]:
    child_env = {key: value for key, value in os.environ.items() if key in _PROCESS_ENV_ALLOWLIST}
    for name, value in server.env.items():
        child_env[name] = _resolve_placeholders(value, env_values)
    return child_env


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except TimeoutError:
        process.kill()
        await process.wait()


def _resolve_placeholders(value: str, env_values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        if name is None:
            return match.group(0)
        return env_values.get(name, "")

    return _ENV_REFERENCE_RE.sub(replace, value)


def missing_placeholder_names(value: object) -> tuple[str, ...]:
    """Return placeholder names in ``value`` for diagnostics."""
    if isinstance(value, str):
        return tuple(extract_env_names_from_text(value))
    return ()
