"""Fake MCP server helpers for runtime tests."""

from __future__ import annotations

import sys
from pathlib import Path


def write_fake_mcp_server(path: Path) -> Path:
    """Write a small stdio MCP server script."""
    script = r"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--name", required=True)
parser.add_argument("--log", required=True)
parser.add_argument("--sleep-call", type=float, default=0.0)
parser.add_argument("--fail-tool")
parser.add_argument("--forbid-env")
parser.add_argument("--require-env")
args = parser.parse_args()
log_path = Path(args.log)
log_path.parent.mkdir(parents=True, exist_ok=True)

def log(event: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{args.name}:{event}\n")

def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()

log("start")
if args.require_env and not os.environ.get(args.require_env):
    log("missing-env")
    raise SystemExit(2)
if args.forbid_env and os.environ.get(args.forbid_env):
    log(f"forbidden-env:{args.forbid_env}")
    raise SystemExit(3)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-11-25", "capabilities": {}}})
    elif method == "notifications/initialized":
        log("initialized")
    elif method == "tools/list":
        log("list-tools")
        send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [{"name": f"{args.name}-tool", "inputSchema": {"type": "object"}}]}})
    elif method == "tools/call":
        tool_name = message.get("params", {}).get("name")
        log(f"call:{tool_name}")
        if args.sleep_call:
            time.sleep(args.sleep_call)
        if tool_name == args.fail_tool:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": "fake tool failed"}})
            continue
        if tool_name == "emit-list-changed":
            send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed", "params": {}})
        send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": args.name}], "isError": False}})
    elif method == "shutdown":
        log("shutdown")
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "exit":
        log("exit")
        raise SystemExit(0)
"""
    path.write_text(script, encoding="utf-8")
    return path


def fake_server_command(
    script: Path,
    *,
    name: str,
    log_path: Path,
    sleep_call: float = 0.0,
    fail_tool: str | None = None,
    forbid_env: str | None = None,
    require_env: str | None = None,
) -> tuple[str, list[str]]:
    """Return a Python command for the fake MCP server."""
    args = [str(script), "--name", name, "--log", str(log_path)]
    if sleep_call:
        args.extend(["--sleep-call", str(sleep_call)])
    if fail_tool:
        args.extend(["--fail-tool", fail_tool])
    if forbid_env:
        args.extend(["--forbid-env", forbid_env])
    if require_env:
        args.extend(["--require-env", require_env])
    return sys.executable, args
