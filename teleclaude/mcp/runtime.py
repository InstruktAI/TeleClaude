"""Daemon-owned lazy MCP lease runtime."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

from dotenv import dotenv_values
from instrukt_ai_logging import get_logger

from teleclaude.config.person_secrets import MissingPersonSecretError, PersonSecretStorageError
from teleclaude.mcp.protocol import JsonObject, McpProtocolError, StdioMcpClient, ToolCatalog
from teleclaude.mcp.registry import (
    McpConcurrency,
    McpCredentialScope,
    McpRegistry,
    McpServerConfig,
    McpTransport,
    RegistryError,
    extract_env_names_from_text,
    load_effective_registry,
    project_mcp_root,
    remote_proxy_command,
)
from teleclaude.mcp.timeouts import (
    MCP_LIST_TOOLS_TIMEOUT_SECONDS,
    MCP_STARTUP_TIMEOUT_SECONDS,
    MCP_TOOL_CALL_TIMEOUT_SECONDS,
)
from teleclaude.paths import ENV_PATH

logger = get_logger(__name__)

_ENV_REFERENCE_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:[:?+\-=][^}]*)?\}|([A-Za-z_][A-Za-z0-9_]*))")
MCP_STDIO_STREAM_LIMIT_BYTES = 1024 * 1024
_INVALID_PROJECT_CONTEXT_CODE = "invalid_project_context"
_INVALID_PROJECT_CONTEXT_MESSAGE = "Invalid project MCP context"
_RUNTIME_CLOSE_FAILED_MESSAGE = "MCP runtime close failed"
_RUNTIME_REAP_FAILED_MESSAGE = "MCP runtime reap failed"
_MACHINE_RUNTIME_IDENTIFIER = "machine"
_PROJECT_RUNTIME_IDENTIFIER_TEMPLATE = "project:{digest}"

type RegistryLoader = Callable[[], McpRegistry]
type PersonSecretResolver = Callable[[str, tuple[str, ...]], dict[str, str]]

_GLOBAL_CREDENTIAL_OWNER = "global"
_PERSON_IDENTITY_REQUIRED_MESSAGE = "MCP server requires verified person identity"
_PERSON_SECRET_UNAVAILABLE_MESSAGE = "Personal MCP credentials are unavailable"


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


@dataclass(frozen=True)
class McpInvocationContext:
    """Verified caller ownership available to a protected MCP invocation."""

    person_slug: str | None = None


@dataclass(frozen=True)
class McpLeaseKey:
    """One owner-isolated MCP lease identity within a project runtime."""

    server_slug: str
    credential_owner: str


@dataclass
class _Lease:
    key: McpLeaseKey
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
        registry_loader: RegistryLoader | None = None,
        person_secret_resolver: PersonSecretResolver | None = None,
        clock: _Clock | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._env_path = env_path
        self._registry = registry
        self._registry_loader = registry_loader
        self._person_secret_resolver = person_secret_resolver
        self._clock = clock
        self._leases: dict[McpLeaseKey, _Lease] = {}
        self._lease_lock = asyncio.Lock()

    def list_servers(self, *, exclude: set[str] | None = None) -> list[JsonObject]:
        """Return the configured server catalog without starting leases."""
        return [server.to_catalog_dict() for server in self._load_registry().enabled_servers(exclude=exclude)]

    async def list_tools(self, slug: str, invocation: McpInvocationContext | None = None) -> JsonObject:
        """Return a server's tool catalog, initializing only that server."""
        lease = await self._lease_for(slug, invocation or McpInvocationContext())
        async with lease.lock:
            try:
                if lease.tools is None or lease.client.tool_list_changed:
                    lease.tools = await asyncio.wait_for(
                        lease.client.list_tools(), timeout=MCP_LIST_TOOLS_TIMEOUT_SECONDS
                    )
            except TimeoutError as exc:
                await self._close_lease(lease.key)
                raise McpRuntimeError("MCP tools/list timed out", code="tool_timeout", slug=slug) from exc
            except _CALLER_SAFE_PROTOCOL_FAILURES as exc:
                raise McpRuntimeError("MCP tools/list failed", code="tool_list_failed", slug=slug) from exc
            self._refresh_deadline(lease)
            return {"server": slug, "tools": lease.tools.tools}

    async def call_tool(
        self,
        slug: str,
        tool_name: str,
        arguments: JsonObject,
        invocation: McpInvocationContext | None = None,
    ) -> JsonObject:
        """Call one tool through the selected server lease."""
        lease = await self._lease_for(slug, invocation or McpInvocationContext())
        async with lease.lock:
            try:
                result = await asyncio.wait_for(
                    lease.client.call_tool(tool_name, arguments),
                    timeout=MCP_TOOL_CALL_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                await self._close_lease(lease.key)
                raise McpRuntimeError("MCP tool call timed out", code="tool_timeout", slug=slug) from exc
            except _CALLER_SAFE_PROTOCOL_FAILURES as exc:
                raise McpRuntimeError("MCP tool call failed", code="tool_call_failed", slug=slug) from exc
            self._refresh_deadline(lease)
            return {"server": slug, "tool": tool_name, "result": result}

    async def reap_idle(self) -> None:
        """Close leases whose idle deadlines have passed."""
        now = self._now()
        expired = [key for key, lease in self._leases.items() if lease.idle_deadline <= now]
        for key in expired:
            await self._close_lease(key)

    async def close(self) -> None:
        """Close all active MCP leases."""
        for key in list(self._leases):
            await self._close_lease(key)

    def active_lease_slugs(self) -> list[str]:
        """Return active lease slugs for diagnostics and tests."""
        return sorted({lease.key.server_slug for lease in self._leases.values()})

    async def _lease_for(self, slug: str, invocation: McpInvocationContext) -> _Lease:
        async with self._lease_lock:
            registry = self._load_registry()
            try:
                server = registry.require_server(slug)
            except RegistryError as exc:
                raise McpRuntimeError(str(exc), code="unknown_server", slug=slug) from exc
            credential_owner, env_values = self._credential_values(server, invocation)
            key = McpLeaseKey(server_slug=slug, credential_owner=credential_owner)
            fingerprint = server.fingerprint(env_values)
            existing = self._leases.get(key)
            if existing is not None and existing.fingerprint == fingerprint:
                self._refresh_deadline(existing)
                return existing
            if existing is not None:
                await self._close_lease(key)
            client = await self._start_client(server, env_values)
            lease = _Lease(
                key=key,
                server=server,
                fingerprint=fingerprint,
                client=client,
                lock=asyncio.Lock() if server.concurrency == McpConcurrency.SERIALIZED else _NullAsyncLock(),
                tools=None,
                idle_deadline=self._now() + server.idle_ttl_seconds,
            )
            self._leases[key] = lease
            return lease

    def _credential_values(
        self, server: McpServerConfig, invocation: McpInvocationContext
    ) -> tuple[str, dict[str, str]]:
        if server.credential_scope is McpCredentialScope.GLOBAL:
            env_values = self._load_env_values()
            missing = tuple(name for name in server.env_references if not env_values.get(name))
            if missing:
                raise McpRuntimeError(
                    "MCP server is missing required environment values",
                    code="missing_env",
                    slug=server.slug,
                    missing_env=missing,
                )
            return _GLOBAL_CREDENTIAL_OWNER, env_values
        person_slug = invocation.person_slug
        if person_slug is None:
            raise McpRuntimeError(
                _PERSON_IDENTITY_REQUIRED_MESSAGE,
                code="person_identity_required",
                slug=server.slug,
            )
        if self._person_secret_resolver is None:
            raise McpRuntimeError(
                _PERSON_SECRET_UNAVAILABLE_MESSAGE,
                code="person_secret_unavailable",
                slug=server.slug,
            )
        try:
            env_values = self._person_secret_resolver(person_slug, server.env_references)
        except MissingPersonSecretError as exc:
            raise McpRuntimeError(
                "MCP server is missing required environment values",
                code="missing_env",
                slug=server.slug,
                missing_env=exc.names,
            ) from exc
        except PersonSecretStorageError as exc:
            raise McpRuntimeError(
                _PERSON_SECRET_UNAVAILABLE_MESSAGE,
                code="person_secret_unavailable",
                slug=server.slug,
            ) from exc
        return person_slug, env_values

    async def _start_client(self, server: McpServerConfig, env_values: dict[str, str]) -> StdioMcpClient:
        process: asyncio.subprocess.Process | None = None
        client: StdioMcpClient | None = None
        try:
            command, args = _launch_command(server)
            resolved_args = _resolve_launch_args(server, args, env_values)
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
                limit=MCP_STDIO_STREAM_LIMIT_BYTES,
            )
            client = StdioMcpClient(process)
            await asyncio.wait_for(client.start(), timeout=MCP_STARTUP_TIMEOUT_SECONDS)
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
        if self._registry is not None:
            return self._registry
        if self._registry_loader is not None:
            return self._registry_loader()
        return load_effective_registry(self._repo_root)

    def _load_env_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if self._env_path.exists():
            for key, value in dotenv_values(self._env_path).items():
                if isinstance(value, str) and value:
                    values[key] = value
        return values

    def _refresh_deadline(self, lease: _Lease) -> None:
        lease.idle_deadline = self._now() + lease.server.idle_ttl_seconds

    async def _close_lease(self, key: McpLeaseKey) -> None:
        lease = self._leases.pop(key, None)
        if lease is None:
            return
        await lease.client.close()

    def _now(self) -> float:
        if self._clock is not None and hasattr(self._clock, "now"):
            return float(self._clock.now())
        return time.monotonic()


class McpRuntimePool:
    """Own per-project MCP runtimes and their isolated lease state."""

    def __init__(
        self,
        *,
        repo_root: Path,
        env_path: Path = ENV_PATH,
        person_secret_resolver: PersonSecretResolver | None = None,
        clock: _Clock | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._env_path = env_path
        self._person_secret_resolver = person_secret_resolver
        self._clock = clock
        self._runtimes: dict[Path, McpRuntime] = {
            repo_root: McpRuntime(
                repo_root=repo_root,
                env_path=env_path,
                person_secret_resolver=person_secret_resolver,
                clock=clock,
            )
        }

    @property
    def machine_runtime(self) -> McpRuntime:
        """Return the permanent machine-wide runtime."""
        return self._runtimes[self._repo_root]

    def runtime_for(self, project_root: Path | None) -> McpRuntime:
        """Return the isolated runtime for a validated project scope."""
        if project_root is None:
            return self.machine_runtime
        try:
            canonical_root = project_mcp_root(project_root)
        except (OSError, ValueError) as exc:
            raise McpRuntimeError(
                _INVALID_PROJECT_CONTEXT_MESSAGE,
                code=_INVALID_PROJECT_CONTEXT_CODE,
            ) from exc
        if canonical_root is None:
            raise McpRuntimeError(
                _INVALID_PROJECT_CONTEXT_MESSAGE,
                code=_INVALID_PROJECT_CONTEXT_CODE,
            )
        runtime = self._runtimes.get(canonical_root)
        if runtime is None:
            runtime = McpRuntime(
                repo_root=self._repo_root,
                env_path=self._env_path,
                registry_loader=lambda: load_effective_registry(self._repo_root, project_root=canonical_root),
                person_secret_resolver=self._person_secret_resolver,
                clock=self._clock,
            )
            self._runtimes[canonical_root] = runtime
        return runtime

    async def reap_idle(self) -> None:
        """Reap idle leases in every runtime without blocking other scopes."""
        for root, runtime in list(self._runtimes.items()):
            try:
                await runtime.reap_idle()
            except Exception as exc:
                logger.warning(
                    _RUNTIME_REAP_FAILED_MESSAGE,
                    runtime_scope=self._runtime_identifier(root),
                    error_type=type(exc).__name__,
                )

    async def close(self) -> None:
        """Close every runtime without blocking cleanup of another scope."""
        for root, runtime in list(self._runtimes.items()):
            try:
                await runtime.close()
            except Exception as exc:
                logger.warning(
                    _RUNTIME_CLOSE_FAILED_MESSAGE,
                    runtime_scope=self._runtime_identifier(root),
                    error_type=type(exc).__name__,
                )

    def _runtime_identifier(self, root: Path) -> str:
        """Return a stable path-free identifier for one pooled runtime."""
        if root == self._repo_root:
            return _MACHINE_RUNTIME_IDENTIFIER
        digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
        return _PROJECT_RUNTIME_IDENTIFIER_TEMPLATE.format(digest=digest)


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
    child_env = {key: value for key, value in os.environ.items() if key in _PROCESS_ENV_ALLOWLIST}  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    for name, value in server.env.items():
        child_env[name] = _resolve_placeholders(value, env_values)
    if server.transport != McpTransport.STDIO:
        for header_value in server.headers.values():
            for name in extract_env_names_from_text(header_value):
                child_env[name] = env_values[name]
    return child_env


def _resolve_launch_args(server: McpServerConfig, args: list[str], env_values: dict[str, str]) -> list[str]:
    if server.transport == McpTransport.STDIO:
        return [_resolve_placeholders(arg, env_values) for arg in args]
    return [
        arg if index > 0 and args[index - 1] == "--header" else _resolve_placeholders(arg, env_values)
        for index, arg in enumerate(args)
    ]


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
