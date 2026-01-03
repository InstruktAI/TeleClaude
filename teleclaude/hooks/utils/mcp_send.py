#!/usr/bin/env python3
"""Send notification to TeleClaude via MCP wrapper (resilient transport)."""

import json
import os
import select
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict

from instrukt_ai_logging import configure_logging, get_logger

# Log to canonical InstruktAI log path for TeleClaude.
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
MCP_WRAPPER = PROJECT_ROOT / "bin" / "mcp-wrapper.py"
HOOK_SEND_TIMEOUT_S = 20.0

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.mcp_send")


def mcp_send(tool: str, payload: Dict[str, Any]) -> None:
    """Invoke tool call in TeleClaude via MCP wrapper (resilient transport).

    Args:
        tool: TeleClaude tool name to invoke
        payload: Arguments for the tool call, MUST contain 'session_id' key
    """
    logger.trace(
        "mcp_send called",
        tool=tool,
        session_id=payload.get("session_id"),
    )

    deadline = time.monotonic() + HOOK_SEND_TIMEOUT_S
    backoffs = [0.5, 1.0, 2.0, 4.0]
    attempt = 0
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            response = _call_wrapper(tool, payload, remaining)
            if "error" in response:
                raise RuntimeError(str(response.get("error")))
            result = response.get("result")
            if isinstance(result, dict) and result.get("isError"):
                raise RuntimeError(str(result.get("content")))
            logger.debug("mcp_send finished", tool=tool)
            return
        except Exception as e:
            last_error = e
            logger.error(
                "mcp_send attempt failed",
                attempt=attempt + 1,
                error=str(e),
                payload=payload,
                traceback=traceback.format_exc(),
            )
            if time.monotonic() >= deadline:
                break
            backoff = backoffs[min(attempt, len(backoffs) - 1)]
            time.sleep(min(backoff, max(0.0, deadline - time.monotonic())))
            attempt += 1

    logger.error(
        "mcp_send failed",
        timeout_s=HOOK_SEND_TIMEOUT_S,
        error=str(last_error),
    )
    raise RuntimeError(f"MCP send failed after {HOOK_SEND_TIMEOUT_S:.0f}s: {last_error}")


def _call_wrapper(tool: str, payload: Dict[str, Any], timeout_s: float) -> Dict[str, Any]:
    """Call the MCP wrapper via stdio and return the tool response."""
    start = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, str(MCP_WRAPPER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
        bufsize=1,
    )

    try:
        if not proc.stdin or not proc.stdout:
            raise RuntimeError("Failed to open MCP wrapper stdio")

        # 1. Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "teleclaude-hook", "version": "1.0.0"},
            },
        }
        _send_line(proc.stdin, init_request)
        _read_json_response(
            proc.stdout,
            timeout_s - (time.monotonic() - start),
            expected_id=init_request["id"],
        )

        # 2. Send initialized notification
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        _send_line(proc.stdin, initialized_notif)

        # 3. Send tool call
        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": payload},
        }
        _send_line(proc.stdin, tool_request)
        response = _read_json_response(
            proc.stdout,
            timeout_s - (time.monotonic() - start),
            expected_id=tool_request["id"],
        )
        logger.debug(
            "mcp_send wrapper response",
            tool=tool,
            session_id=payload.get("session_id"),
            pid=proc.pid,
            elapsed=round(time.monotonic() - start, 3),
        )
        return response
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
            logger.debug(
                "mcp_send wrapper exit",
                tool=tool,
                session_id=payload.get("session_id"),
                pid=proc.pid,
                returncode=proc.returncode,
            )
        except Exception:
            try:
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except Exception:
                        pass
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                proc.kill()


def _send_line(stream: Any, message: Dict[str, Any]) -> None:
    line = json.dumps(message) + "\n"
    stream.write(line)
    stream.flush()


def _read_json_response(stream: Any, timeout_s: float, expected_id: object) -> Dict[str, Any]:
    if timeout_s <= 0:
        raise TimeoutError("Timeout waiting for MCP wrapper response")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([stream], [], [], remaining)
        if ready:
            line = stream.readline()
            if not line:
                raise TimeoutError("MCP wrapper closed stdout")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON from MCP wrapper: {line!r}") from exc

            if not isinstance(message, dict):
                raise RuntimeError(f"Invalid MCP wrapper response: {message!r}")

            if "id" not in message:
                # Notifications may arrive at any time; ignore and keep reading.
                continue

            if message.get("id") != expected_id:
                # Responses can arrive out-of-order; ignore unrelated IDs.
                logger.debug(
                    "Ignoring unexpected MCP response id",
                    got=message.get("id"),
                    expected=expected_id,
                )
                continue
            return message
    raise TimeoutError("Timeout waiting for MCP wrapper response")
