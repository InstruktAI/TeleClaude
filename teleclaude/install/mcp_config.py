"""Load and normalize native-published MCP server config for agent CLI installers."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from teleclaude.mcp.registry import load_effective_registry, load_native_publish_servers

MCP_CONFIG_FILE = "mcp.json"
MCP_LOCAL_CONFIG_FILE = "mcp.local.json"
MCP_REMOTE_PACKAGE = "mcp-remote@latest"
REMOTE_MCP_TYPES = frozenset({"http", "sse", "streamable-http", "streamable_http"})

_ENV_REFERENCE_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:[:?+\-=][^}]*)?\}|([A-Za-z_][A-Za-z0-9_]*))")
_SHELL_ENV_REFERENCE_NAMES = frozenset({"HOME", "LOGNAME", "PATH", "PWD", "SHELL", "TEMP", "TMP", "TMPDIR", "USER"})

type JsonObject = dict[str, object]  # guard: loose-dict - MCP JSON config objects are dynamic by server.
type McpServers = dict[str, JsonObject]


def _optional_object(settings: JsonObject, key: str, *, label: str) -> JsonObject:
    if key not in settings:
        return {}
    value = settings[key]
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid {label}: {key} must be an object.")
    return dict(value)


def _extract_env_names_from_text(text: str) -> list[str]:
    names: list[str] = []
    for match in _ENV_REFERENCE_RE.finditer(text):
        env_name = match.group(1) or match.group(2)
        if env_name and env_name not in _SHELL_ENV_REFERENCE_NAMES:
            names.append(env_name)
    return names


def _add_env_name(names: list[str], seen: set[str], name: str) -> None:
    if name in _SHELL_ENV_REFERENCE_NAMES or name in seen:
        return
    seen.add(name)
    names.append(name)


def _mcp_env_template_map(name: str, spec: JsonObject) -> dict[str, str]:
    raw_env = spec.get("env")
    if raw_env is None:
        return {}
    if not isinstance(raw_env, dict):
        raise RuntimeError(f"Invalid MCP server {name}: env must be an object.")

    env: dict[str, str] = {}
    for key, value in raw_env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError(f"Invalid MCP server {name}: env must map strings to strings.")
        env[key] = value
    return env


def _exact_env_reference(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    match = _ENV_REFERENCE_RE.fullmatch(stripped)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _shell_env_assignment_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`") + '"'


def _mcp_env_requirements(name: str, spec: JsonObject) -> tuple[list[str], list[tuple[str, str]]]:
    required_names: list[str] = []
    assignments: list[tuple[str, str]] = []
    seen_required: set[str] = set()
    seen_assignments: set[str] = set()

    env_templates = _mcp_env_template_map(name, spec)
    all_env_refs = extract_env_references({name: spec})
    if not all_env_refs:
        return [], []
    for env_name in all_env_refs:
        _add_env_name(required_names, seen_required, env_name)

    for target_name, template_value in env_templates.items():
        source_name = _exact_env_reference(template_value)
        if source_name:
            assignment_value = f'"${{{source_name}}}"'
        elif _extract_env_names_from_text(template_value):
            assignment_value = _shell_env_assignment_value(template_value)
        else:
            assignment_value = shlex.quote(template_value)

        if target_name not in seen_assignments:
            seen_assignments.add(target_name)
            assignments.append((target_name, assignment_value))

    non_env_spec = {key: value for key, value in spec.items() if key != "env"}
    for env_name in extract_env_references({name: non_env_spec}):
        _add_env_name(required_names, seen_required, env_name)
        if env_name not in seen_assignments:
            seen_assignments.add(env_name)
            assignments.append((env_name, f'"${{{env_name}}}"'))

    return required_names, assignments


def _self_sourcing_mcp_server(
    name: str, spec: JsonObject, command_parts: list[str], *, preserve: JsonObject | None = None
) -> JsonObject:
    script_parts = ['source "$HOME/.teleclaude/.env"']
    required_names, assignments = _mcp_env_requirements(name, spec)
    for env_name in required_names:
        script_parts.append(f'[ -n "${{{env_name}:-}}" ] || {{ echo "Missing {env_name}" >&2; exit 1; }}')

    wrapped_parts = ["exec"]
    if assignments:
        wrapped_parts.append("env")
        wrapped_parts.extend(f"{target_name}={assignment_value}" for target_name, assignment_value in assignments)
    wrapped_parts.extend(command_parts)

    script_parts.append(" ".join(wrapped_parts))
    wrapped: JsonObject = {"command": "bash", "args": ["-lc", "; ".join(script_parts)]}
    if preserve:
        wrapped = {**preserve, **wrapped}
    return wrapped


def _normalize_remote_mcp_server(name: str, spec: JsonObject, url: str) -> JsonObject:
    headers = _optional_object(spec, "headers", label=f"MCP server {name}") if "headers" in spec else {}
    direct_args = ["-y", MCP_REMOTE_PACKAGE, url]
    command_parts = ["npx", "-y", MCP_REMOTE_PACKAGE, shlex.quote(url)]
    for header_name, header_value in headers.items():
        if not isinstance(header_value, str):
            raise RuntimeError(f"Invalid MCP server {name}: headers must map strings to strings.")
        direct_args.extend(["--header", f"{header_name}: {header_value}"])
        command_parts.extend(["--header", shlex.quote(f"{header_name}: {header_value}")])

    server_type = spec.get("type")
    if server_type == "sse":
        direct_args.extend(["--transport", "sse-only"])
        command_parts.extend(["--transport", "sse-only"])
    elif server_type in {"http", "streamable-http", "streamable_http"}:
        direct_args.extend(["--transport", "http-only"])
        command_parts.extend(["--transport", "http-only"])

    if not extract_env_references({name: spec}):
        direct: JsonObject = {"command": "npx", "args": direct_args}
        if "env" in spec:
            direct["env"] = spec["env"]
        return direct

    return _self_sourcing_mcp_server(name, spec, command_parts)


def _normalize_stdio_mcp_server(name: str, spec: JsonObject) -> JsonObject:
    command = spec.get("command")
    if not isinstance(command, str):
        raise RuntimeError(f"Invalid MCP server {name}: command must be a string.")

    args = spec.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise RuntimeError(f"Invalid MCP server {name}: args must be an array of strings.")

    preserve = {key: value for key, value in spec.items() if key not in {"command", "args", "env"}}
    command_parts = [shlex.quote(command), *(shlex.quote(arg) for arg in args)]
    return _self_sourcing_mcp_server(name, spec, command_parts, preserve=preserve)


def _normalize_mcp_servers(mcp_servers: McpServers) -> McpServers:
    normalized: McpServers = {}
    for name, spec in mcp_servers.items():
        if "command" in spec:
            if extract_env_references({name: spec}):
                normalized[name] = _normalize_stdio_mcp_server(name, spec)
            else:
                normalized[name] = dict(spec)
            continue

        url = spec.get("url")
        server_type = spec.get("type")
        if isinstance(url, str):
            normalized[name] = _normalize_remote_mcp_server(name, spec, url)
            continue
        if isinstance(server_type, str) and server_type in REMOTE_MCP_TYPES:
            raise RuntimeError(f"Invalid MCP server {name}: remote MCP servers require a url.")
        normalized[name] = dict(spec)
    return normalized


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


def extract_env_references(mcp_servers_spec: McpServers) -> list[str]:
    """Return env var names referenced by MCP server definitions."""
    names: list[str] = []
    seen: set[str] = set()
    for spec in mcp_servers_spec.values():
        for text in _iter_strings(_launch_reference_spec(spec)):
            for env_name in _extract_env_names_from_text(text):
                _add_env_name(names, seen, env_name)
    return names


def _launch_reference_spec(spec: JsonObject) -> JsonObject:
    return {key: spec[key] for key in ("command", "args", "url", "headers", "env") if key in spec}


def load_managed_mcp_servers(repo_root: Path) -> McpServers:
    """Load compatibility MCP servers explicitly opted into native publication."""
    return _normalize_mcp_servers(load_native_publish_servers(repo_root))


def load_managed_mcp_server_names(repo_root: Path) -> set[str]:
    """Return all TeleClaude-owned MCP server slugs from the effective registry."""
    return set(load_effective_registry(repo_root).servers)
