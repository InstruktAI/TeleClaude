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
import subprocess
import sys
from collections.abc import Mapping, Sequence

import httpx

from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.session_identity import get_session_id, get_session_token

_TUI_SESSION_NAME = "tc_tui"
_API_SOCKET_ENV = "TELECLAUDE_API_SOCKET_PATH"
type QueryParamValue = str | int | float | bool | None
type ToolQueryParams = (
    Mapping[str, QueryParamValue | Sequence[QueryParamValue]]
    | list[tuple[str, QueryParamValue]]
    | tuple[tuple[str, QueryParamValue], ...]
)


class ToolAPIError(Exception):
    """Structured transport/API error for long-running wrapper workflows."""

    def __init__(self, message: str, *, status_code: int | None = None, is_timeout: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.is_timeout = is_timeout


def _read_tmux_session_name() -> str | None:
    """Query tmux server for current session name.

    Uses `tmux display-message -p '#S'` which asks the tmux server process —
    not an env var. The agent cannot forge this value from within the session.
    Returns None if not running inside tmux or tmux is unavailable.
    """
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def tool_api_request(
    method: str,
    path: str,
    json_body: object = None,
    params: ToolQueryParams | None = None,
    timeout: float = 30.0,
    socket_path: str | None = None,
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
    resolved_socket_path = socket_path or os.environ.get(_API_SOCKET_ENV, API_SOCKET_PATH)
    tmux_session = _read_tmux_session_name()
    use_session_identity = tmux_session != _TUI_SESSION_NAME
    session_id = get_session_id() if use_session_identity else None
    terminal_email = read_current_session_email()

    headers: dict[str, str] = {}
    token = get_session_token() if use_session_identity else None
    if token:
        headers["x-session-token"] = token
    if session_id:
        headers["x-caller-session-id"] = session_id
    if terminal_email:
        headers["x-telec-email"] = terminal_email
    if tmux_session:
        headers["x-tmux-session"] = tmux_session

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
        raise ToolAPIError(f"daemon is not running (socket not found: {resolved_socket_path})")
    except httpx.TimeoutException:
        raise ToolAPIError("request timed out", is_timeout=True)
    except Exception as exc:
        raise ToolAPIError(str(exc))

    if resp.status_code == 401:
        detail = _extract_detail(resp)
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
