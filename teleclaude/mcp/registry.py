"""TeleClaude MCP registry model and loader."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from teleclaude.mcp.jsonc import JsoncError, JsonObject, load_jsonc_object

TELECLAUDE_MCP_CONFIG_FILE = "teleclaude-mcp.jsonc"
TELECLAUDE_MCP_LOCAL_CONFIG_FILE = "teleclaude-mcp.local.jsonc"
COMPAT_MCP_CONFIG_FILE = "mcp.json"
COMPAT_MCP_LOCAL_CONFIG_FILE = "mcp.local.json"
MCP_REMOTE_PACKAGE = "mcp-remote@0.1.38"
DEFAULT_IDLE_TTL_SECONDS = 900.0
SCHEMA_PATH = "schemas/teleclaude-mcp.schema.json"

_ENV_REFERENCE_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:[:?+\-=][^}]*)?\}|([A-Za-z_][A-Za-z0-9_]*))")
_SHELL_ENV_REFERENCE_NAMES = frozenset({"HOME", "LOGNAME", "PATH", "PWD", "SHELL", "TEMP", "TMP", "TMPDIR", "USER"})
_REMOVED_TIMEOUT_KEYS = frozenset(
    {"startupTimeoutSec", "startupTimeoutSeconds", "toolTimeoutSec", "toolTimeoutSeconds"}
)

type McpServers = dict[str, JsonObject]


class RegistryError(ValueError):
    """Raised when the effective MCP registry violates its contract."""


class McpTransport(StrEnum):
    """Supported MCP transport kinds."""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class McpConcurrency(StrEnum):
    """Per-server request concurrency mode."""

    SERIALIZED = "serialized"
    PARALLEL = "parallel"


@dataclass(frozen=True)
class McpServerConfig:
    """A normalized TeleClaude MCP server definition."""

    slug: str
    trigger: str | None = None
    transport: McpTransport = McpTransport.STDIO
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    lazy: bool = True
    idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS
    concurrency: McpConcurrency = McpConcurrency.SERIALIZED

    @property
    def env_references(self) -> tuple[str, ...]:
        """Environment variable names referenced by this server definition."""
        names: list[str] = []
        seen: set[str] = set()
        for value in _iter_strings(self.to_launch_dict()):
            for name in extract_env_names_from_text(value):
                if name not in seen:
                    seen.add(name)
                    names.append(name)
        return tuple(names)

    def to_catalog_dict(self) -> JsonObject:
        """Return a secret-safe catalog representation."""
        data: JsonObject = {
            "slug": self.slug,
            "trigger": self.trigger or "",
            "transport": self.transport.value,
            "enabled": self.enabled,
            "lazy": self.lazy,
            "requiresEnv": list(self.env_references),
        }
        return data

    def to_wire_dict(self) -> JsonObject:
        """Return the normalized registry shape without derived runtime state."""
        data: JsonObject = {
            "enabled": self.enabled,
            "transport": self.transport.value,
            "lazy": {
                "enabled": self.lazy,
                "idleTtlSec": self.idle_ttl_seconds,
                "concurrency": self.concurrency.value,
            },
        }
        if self.trigger is not None:
            data["trigger"] = self.trigger
        if self.command is not None:
            data["command"] = self.command
        if self.args:
            data["args"] = list(self.args)
        if self.url is not None:
            data["url"] = self.url
        if self.headers:
            data["headers"] = dict(self.headers)
        if self.env:
            data["env"] = dict(self.env)
        return data

    def to_launch_dict(self) -> JsonObject:
        """Return only fields that affect server startup and remote connection."""
        data: JsonObject = {"transport": self.transport.value}
        if self.command is not None:
            data["command"] = self.command
        if self.args:
            data["args"] = list(self.args)
        if self.url is not None:
            data["url"] = self.url
        if self.headers:
            data["headers"] = dict(self.headers)
        if self.env:
            data["env"] = dict(self.env)
        return data

    def to_fingerprint_dict(self) -> JsonObject:
        """Return normalized config fields that affect warm lease reuse."""
        data = self.to_wire_dict()
        data.pop("trigger", None)
        return data

    def fingerprint(self, env_values: dict[str, str]) -> str:
        """Hash the effective launch config and referenced environment values."""
        payload = {
            "server": self.to_fingerprint_dict(),
            "env": {name: env_values.get(name, "") for name in self.env_references},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class McpRegistry:
    """Effective MCP registry for a project root."""

    servers: dict[str, McpServerConfig]

    def enabled_servers(self, *, exclude: set[str] | None = None) -> list[McpServerConfig]:
        """Return enabled servers sorted by slug."""
        excluded = exclude or set()
        return [server for slug, server in sorted(self.servers.items()) if server.enabled and slug not in excluded]

    def require_server(self, slug: str) -> McpServerConfig:
        """Return one enabled server or raise a caller-safe error."""
        server = self.servers.get(slug)
        if server is None or not server.enabled:
            raise RegistryError(f"Unknown MCP server: {slug}")
        return server


def load_effective_registry(repo_root: Path) -> McpRegistry:
    """Load the merged TeleClaude MCP registry for ``repo_root``."""
    servers = _load_effective_server_specs(repo_root)
    return McpRegistry(servers={slug: _parse_server(slug, spec) for slug, spec in servers.items()})


def extract_env_names_from_text(text: str) -> list[str]:
    """Return non-shell env var names referenced in ``text``."""
    names: list[str] = []
    for match in _ENV_REFERENCE_RE.finditer(text):
        env_name = match.group(1) or match.group(2)
        if env_name and env_name not in _SHELL_ENV_REFERENCE_NAMES:
            names.append(env_name)
    return names


def extract_env_references(mcp_servers_spec: McpServers) -> list[str]:
    """Return env var names referenced by MCP server definitions."""
    names: list[str] = []
    seen: set[str] = set()
    for spec in mcp_servers_spec.values():
        for text in _iter_strings(launch_reference_spec(spec)):
            for env_name in extract_env_names_from_text(text):
                if env_name not in seen:
                    seen.add(env_name)
                    names.append(env_name)
    return names


def launch_reference_spec(spec: JsonObject) -> JsonObject:
    return {key: spec[key] for key in ("command", "args", "url", "headers", "env") if key in spec}


def _load_effective_server_specs(repo_root: Path) -> McpServers:
    shared_path = repo_root / TELECLAUDE_MCP_CONFIG_FILE
    local_path = repo_root / TELECLAUDE_MCP_LOCAL_CONFIG_FILE
    compat_shared_path = repo_root / COMPAT_MCP_CONFIG_FILE
    compat_local_path = repo_root / COMPAT_MCP_LOCAL_CONFIG_FILE

    compat = _merge_mcp_servers(
        _read_compat_servers(compat_shared_path, required=not shared_path.exists()),
        _read_compat_servers(compat_local_path, required=False),
    )
    canonical = _merge_mcp_servers(
        _read_teleclaude_servers(shared_path, required=False),
        _read_teleclaude_servers(local_path, required=False),
    )
    return _merge_mcp_servers(compat, canonical)


def _read_teleclaude_servers(path: Path, *, required: bool) -> McpServers:
    try:
        settings = load_jsonc_object(path, required=required)
    except JsoncError as exc:
        raise RegistryError(str(exc)) from exc
    return _servers_from_wrapper(settings, key="servers", label=f"TeleClaude MCP registry {path}")


def _read_compat_servers(path: Path, *, required: bool) -> McpServers:
    try:
        settings = load_jsonc_object(path, required=required)
    except JsoncError as exc:
        raise RegistryError(str(exc)) from exc
    return _servers_from_wrapper(settings, key="mcpServers", label=f"compat MCP registry {path}")


def _servers_from_wrapper(settings: JsonObject, *, key: str, label: str) -> McpServers:
    if not settings:
        return {}
    value = settings.get(key, {})
    if not isinstance(value, dict):
        raise RegistryError(f"Invalid {label}: {key} must be an object.")
    servers: McpServers = {}
    for slug, spec in value.items():
        if not isinstance(slug, str) or not isinstance(spec, dict):
            raise RegistryError(f"Invalid {label}: every MCP server must be an object.")
        servers[slug] = dict(spec)
    return servers


def _parse_server(slug: str, spec: JsonObject) -> McpServerConfig:
    if "nativePublish" in spec:
        raise RegistryError(
            f"Invalid MCP server {slug}: nativePublish was removed; "
            "native agent MCP configs are not a publication target."
        )
    transport = _parse_transport(slug, spec)
    lazy = _parse_lazy(slug, spec)
    args = _optional_string_list(slug, spec, "args")
    headers = _optional_string_map(slug, spec, "headers")
    env = _optional_string_map(slug, spec, "env")
    command = _optional_string(slug, spec, "command")
    url = _optional_string(slug, spec, "url")
    if transport == McpTransport.STDIO and command is None:
        raise RegistryError(f"Invalid MCP server {slug}: stdio servers require command.")
    if transport != McpTransport.STDIO and url is None:
        raise RegistryError(f"Invalid MCP server {slug}: remote MCP servers require url.")
    return McpServerConfig(
        slug=slug,
        trigger=_optional_string(slug, spec, "trigger"),
        transport=transport,
        command=command,
        args=tuple(args),
        url=url,
        headers=headers,
        env=env,
        enabled=_optional_bool(slug, spec, "enabled", default=True),
        lazy=lazy.enabled,
        idle_ttl_seconds=lazy.idle_ttl_seconds,
        concurrency=lazy.concurrency,
    )


def _parse_transport(slug: str, spec: JsonObject) -> McpTransport:
    raw = spec.get("transport", spec.get("type", "stdio"))
    if raw == "streamable_http":
        raw = McpTransport.STREAMABLE_HTTP.value
    try:
        return McpTransport(str(raw))
    except ValueError as exc:
        raise RegistryError(f"Invalid MCP server {slug}: unsupported transport {raw!r}.") from exc


@dataclass(frozen=True)
class _LazyConfig:
    enabled: bool
    idle_ttl_seconds: float
    concurrency: McpConcurrency


def _parse_lazy(slug: str, spec: JsonObject) -> _LazyConfig:
    raw = spec.get("lazy", {})
    if isinstance(raw, bool):
        lazy_spec: JsonObject = {"enabled": raw}
    elif isinstance(raw, dict):
        lazy_spec = dict(raw)
    else:
        raise RegistryError(f"Invalid MCP server {slug}: lazy must be an object.")
    _reject_removed_timeout_options(slug, spec, lazy_spec)
    return _LazyConfig(
        enabled=_optional_bool(slug, lazy_spec, "enabled", default=True),
        idle_ttl_seconds=_lazy_number(
            slug, spec, lazy_spec, key="idleTtlSec", legacy_key="idleTtlSeconds", default=DEFAULT_IDLE_TTL_SECONDS
        ),
        concurrency=_optional_concurrency(slug, lazy_spec if "concurrency" in lazy_spec else spec),
    )


def _reject_removed_timeout_options(slug: str, spec: JsonObject, lazy_spec: JsonObject) -> None:
    for key in sorted(_REMOVED_TIMEOUT_KEYS):
        if key in spec or key in lazy_spec:
            raise RegistryError(f"Invalid MCP server {slug}: MCP operation timeouts are fixed daemon defaults.")


def _lazy_number(
    slug: str, spec: JsonObject, lazy_spec: JsonObject, *, key: str, legacy_key: str, default: float
) -> float:
    if key in lazy_spec:
        return _optional_number(slug, lazy_spec, key, default)
    return _optional_number(slug, spec, legacy_key, default)


def _optional_string(slug: str, spec: JsonObject, key: str) -> str | None:
    value = spec.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegistryError(f"Invalid MCP server {slug}: {key} must be a string.")
    return value


def _optional_string_list(slug: str, spec: JsonObject, key: str) -> list[str]:
    value = spec.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RegistryError(f"Invalid MCP server {slug}: {key} must be an array of strings.")
    return list(cast(list[str], value))


def _optional_string_map(slug: str, spec: JsonObject, key: str) -> dict[str, str]:
    value = spec.get(key, {})
    if not isinstance(value, dict):
        raise RegistryError(f"Invalid MCP server {slug}: {key} must be an object.")
    result: dict[str, str] = {}
    for name, item in value.items():
        if not isinstance(name, str) or not isinstance(item, str):
            raise RegistryError(f"Invalid MCP server {slug}: {key} must map strings to strings.")
        result[name] = item
    return result


def _optional_bool(slug: str, spec: JsonObject, key: str, *, default: bool) -> bool:
    value = spec.get(key, default)
    if not isinstance(value, bool):
        raise RegistryError(f"Invalid MCP server {slug}: {key} must be a boolean.")
    return value


def _optional_number(slug: str, spec: JsonObject, key: str, default: float) -> float:
    value = spec.get(key, default)
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise RegistryError(f"Invalid MCP server {slug}: {key} must be a positive number.")
    return float(value)


def _optional_concurrency(slug: str, spec: JsonObject) -> McpConcurrency:
    value = spec.get("concurrency", McpConcurrency.SERIALIZED.value)
    try:
        return McpConcurrency(str(value))
    except ValueError as exc:
        raise RegistryError(f"Invalid MCP server {slug}: concurrency must be serialized or parallel.") from exc


def _merge_mcp_servers(base: McpServers, local: McpServers) -> McpServers:
    merged = {name: dict(spec) for name, spec in base.items()}
    for name, local_spec in local.items():
        existing = merged.get(name)
        if existing is not None:
            merged[name] = _deep_merge(existing, local_spec)
        else:
            merged[name] = dict(local_spec)
    return merged


def _deep_merge(base: JsonObject, overrides: JsonObject) -> JsonObject:
    merged = base.copy()
    for key, value in overrides.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(cast(JsonObject, merged[key]), cast(JsonObject, value))
        else:
            merged[key] = value
    return merged


def _iter_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_iter_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_iter_strings(item))
        return strings
    return []


def remote_proxy_command(server: McpServerConfig) -> tuple[str, list[str]]:
    """Build the stdio proxy command for a remote MCP server."""
    if server.url is None:
        raise RegistryError(f"Invalid MCP server {server.slug}: remote MCP servers require url.")
    args = ["-y", MCP_REMOTE_PACKAGE, server.url]
    for header_name, header_value in server.headers.items():
        args.extend(["--header", f"{header_name}: {_normalize_env_placeholders(header_value)}"])
    if server.transport == McpTransport.SSE:
        args.extend(["--transport", "sse-only"])
    else:
        args.extend(["--transport", "http-only"])
    return "npx", args


def _normalize_env_placeholders(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return f"${{{name}}}" if name is not None else match.group(0)

    return _ENV_REFERENCE_RE.sub(replace, value)
