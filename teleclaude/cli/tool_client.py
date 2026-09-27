"""Synchronous HTTP client for telec tool subcommands.

One-shot requests to the daemon REST API over the Unix socket.
Sends identity headers with each call:
  X-Session-Token:     from $TMPDIR/teleclaude_identity.json (agent sessions only)
  X-Caller-Session-Id: from $TMPDIR/teleclaude_identity.json (agent sessions only)
  X-Telec-Email:       from per-TTY telec login state
  X-Tmux-Session:      from tmux server (unforgeable by agent)
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from teleclaude.constants import API_SOCKET_PATH, LOGIN_REQUIRED_DETAIL

if TYPE_CHECKING:
    from teleclaude.cli.clearance import ClearanceScope
    from teleclaude.cli.session_auth import ResolvedCliIdentity

_API_SOCKET_ENV = "TELECLAUDE_API_SOCKET_PATH"
_PROJECT_ROOT_HEADER = "x-teleclaude-project-root"
type QueryParamValue = str | int | float | bool | None
type ToolQueryParams = (
    Mapping[str, QueryParamValue | Sequence[QueryParamValue]]
    | list[tuple[str, QueryParamValue]]
    | tuple[tuple[str, QueryParamValue], ...]
)


class ToolAPIError(Exception):
    """Structured transport/API error for long-running wrapper workflows."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_timeout: bool = False,
        is_unavailable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.is_timeout = is_timeout
        self.is_unavailable = is_unavailable


def tool_api_request(
    method: str,
    path: str,
    json_body: object = None,
    params: ToolQueryParams | None = None,
    timeout: float = 30.0,
    socket_path: str | None = None,
    project_root: Path | None = None,
    clearance_scope: ClearanceScope | None = None,
    clearance_identity: ResolvedCliIdentity | None = None,
) -> object:
    """Make a synchronous API call to the daemon.

    Reads caller identity from TMPDIR and tmux server, sends dual-factor
    headers, and returns the parsed JSON response.

    Args:
        method: HTTP method (GET, POST, DELETE, etc.)
        path: URL path (e.g. "/sessions")
        json_body: Request body (serialized as JSON)
        params: Query parameters
        timeout: Request timeout in seconds
        socket_path: Path to Unix socket

    Returns:
        Parsed JSON response as dict or list.

    Raises:
        ToolAPIError: On daemon unavailability, timeout, or HTTP error response.
    """
    resolved_socket_path = socket_path or os.environ.get(_API_SOCKET_ENV, API_SOCKET_PATH)  # fmt: skip  # guard: direct-env-read - temporary migration: config-tunables-via-config
    scoped_identity: ResolvedCliIdentity | None = None
    if clearance_scope is not None:
        from teleclaude.cli.clearance import (  # noqa: PLC0415 - TUI call sites supply an explicit authorization scope.
            clearance_scope_refusal,
            refresh_cli_identity_role,
        )
        from teleclaude.cli.session_auth import (  # noqa: PLC0415 - resolve only when a caller omitted the TUI snapshot.
            resolve_cli_identity,
        )

        scoped_identity = refresh_cli_identity_role(clearance_identity or resolve_cli_identity())
        refusal = clearance_scope_refusal(clearance_scope, scoped_identity)
        if refusal is not None:
            raise ToolAPIError(refusal, status_code=403)
    from teleclaude.caller_identity import (  # noqa: PLC0415 - request construction owns caller serialization.
        CarriedIdentity,
    )
    from teleclaude.core.operation_caller_identity import (  # noqa: PLC0415 - operation context is a request-time input.
        get_caller_session_id,
    )

    operation_session_id = get_caller_session_id()
    if operation_session_id is not None:
        from teleclaude.core.session_identity_facts import (  # noqa: PLC0415 - operation identity uses the published lean row read.
            read_session_identity_facts,
        )
        from teleclaude.paths import MAIN_DB_PATH  # noqa: PLC0415 - operation identity uses the active session store.

        session_facts = read_session_identity_facts(str(MAIN_DB_PATH), operation_session_id)
        carried = CarriedIdentity.from_session_facts(session_facts) if session_facts is not None else CarriedIdentity()
    else:
        from teleclaude.cli.session_auth import (  # noqa: PLC0415 - caller resolution is needed only at request time.
            resolve_cli_identity,
        )

        carried = CarriedIdentity.from_cli_identity(scoped_identity or resolve_cli_identity())
    headers = carried.to_headers()
    if project_root is not None:
        headers[_PROJECT_ROOT_HEADER] = str(project_root)

    try:
        transport = httpx.HTTPTransport(uds=resolved_socket_path)
        with httpx.Client(
            transport=transport,
            base_url="http://localhost",
            timeout=timeout,
        ) as client:
            resp = client.request(
                method,
                path,
                json=json_body,
                params=params,
                headers=headers,
            )
    except httpx.ConnectError:
        raise ToolAPIError(
            f"daemon is not running (socket not found: {resolved_socket_path})",
            is_unavailable=True,
        )
    except httpx.TimeoutException:
        raise ToolAPIError("request timed out", is_timeout=True)
    except Exception as exc:
        raise ToolAPIError(str(exc))

    if resp.status_code == 401:
        detail = _extract_detail(resp)
        if detail == LOGIN_REQUIRED_DETAIL:
            raise ToolAPIError(f"{detail}. Run: telec auth login <email>", status_code=401)
        raise ToolAPIError(f"authentication required — {detail}", status_code=401)
    if resp.status_code == 403:
        detail = _extract_detail(resp)
        raise ToolAPIError(f"permission denied — {detail}", status_code=403)
    if resp.status_code >= 400:
        detail = _extract_detail(resp)
        raise ToolAPIError(f"{resp.status_code} — {detail}", status_code=resp.status_code)

    try:
        return resp.json()
    except Exception:
        return resp.text


def tool_api_call(
    method: str,
    path: str,
    json_body: object = None,
    params: ToolQueryParams | None = None,
    timeout: float = 30.0,
    socket_path: str | None = None,
    project_root: Path | None = None,
    clearance_scope: ClearanceScope | None = None,
    clearance_identity: ResolvedCliIdentity | None = None,
) -> object:
    """Make a synchronous API call and exit on failure."""
    try:
        return tool_api_request(
            method,
            path,
            json_body=json_body,
            params=params,
            timeout=timeout,
            socket_path=socket_path,
            project_root=project_root,
            clearance_scope=clearance_scope,
            clearance_identity=clearance_identity,
        )
    except ToolAPIError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from exc


def _extract_detail(resp: httpx.Response) -> str:
    """Extract error detail from response body."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("detail", resp.text))
    except Exception:
        pass
    return resp.text


def print_json(data: object) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))
