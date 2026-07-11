"""Minimal MCP stdio JSON-RPC client."""

from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import Process
from dataclasses import dataclass

MCP_PROTOCOL_VERSION = "2025-11-25"

type JsonObject = dict[str, object]  # guard: loose-dict - JSON-RPC payloads are schema-bound at MCP boundary.


class McpProtocolError(RuntimeError):
    """Raised for malformed or failed MCP protocol exchanges."""


@dataclass(frozen=True)
class ToolCatalog:
    """Tool catalog returned by an MCP server."""

    tools: list[JsonObject]


class StdioMcpClient:
    """Request/response client for one stdio MCP process."""

    def __init__(self, process: Process) -> None:
        self._process = process
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._tool_list_changed = False

    @property
    def tool_list_changed(self) -> bool:
        """Whether the server reported a changed tool list."""
        return self._tool_list_changed

    async def start(self) -> None:
        """Start the response reader and perform MCP initialization."""
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "teleclaude", "version": "0.6.1"},
            },
        )
        await self._notify("notifications/initialized", {})

    async def list_tools(self) -> ToolCatalog:
        """Return all tools, following MCP pagination cursors."""
        tools: list[JsonObject] = []
        cursor: object | None = None
        self._tool_list_changed = False
        while True:
            params: JsonObject = {}
            if isinstance(cursor, str):
                params["cursor"] = cursor
            result = await self._request("tools/list", params)
            raw_tools = result.get("tools", [])
            if not isinstance(raw_tools, list):
                raise McpProtocolError("MCP tools/list result must include a tools array")
            for tool in raw_tools:
                if not isinstance(tool, dict):
                    raise McpProtocolError("MCP tool entries must be objects")
                tools.append(dict(tool))
            cursor = result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        return ToolCatalog(tools=tools)

    async def call_tool(self, name: str, arguments: JsonObject) -> JsonObject:
        """Call one MCP tool by name."""
        return await self._request("tools/call", {"name": name, "arguments": arguments})

    async def close(self) -> None:
        """Close the MCP process, preferring graceful shutdown."""
        exit_notified = False
        if self._process.returncode is None:
            try:
                await asyncio.wait_for(self._request("shutdown", {}), timeout=1)
                await self._notify("exit", {})
                exit_notified = True
            except (TimeoutError, McpProtocolError, BrokenPipeError):
                pass
        if self._process.returncode is None and exit_notified:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=1)
            except TimeoutError:
                pass
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=1)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            except McpProtocolError:
                pass

    async def _request(self, method: str, params: JsonObject) -> JsonObject:
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[JsonObject] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return await future
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            raise
        except Exception:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            raise

    async def _notify(self, method: str, params: JsonObject) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, payload: JsonObject) -> None:
        if self._process.stdin is None:
            raise McpProtocolError("MCP process stdin is unavailable")
        self._process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        if self._process.stdout is None:
            raise McpProtocolError("MCP process stdout is unavailable")
        while True:
            try:
                line = await self._process.stdout.readline()
            except ValueError as exc:
                self._fail_pending(f"MCP stdout read failed: {exc}")
                return
            if not line:
                self._fail_pending("MCP process closed stdout")
                return
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            method = message.get("method")
            if method == "notifications/tools/list_changed":
                self._tool_list_changed = True
                continue
            raw_id = message.get("id")
            if not isinstance(raw_id, int):
                continue
            future = self._pending.pop(raw_id, None)
            if future is None or future.done():
                continue
            error = message.get("error")
            if isinstance(error, dict):
                future.set_exception(McpProtocolError(str(error.get("message", "MCP request failed"))))
                continue
            result = message.get("result", {})
            if not isinstance(result, dict):
                future.set_exception(McpProtocolError("MCP response result must be an object"))
                continue
            future.set_result(dict(result))

    def _fail_pending(self, message: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpProtocolError(message))
        self._pending.clear()
