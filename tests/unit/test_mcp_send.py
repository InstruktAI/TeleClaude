"""Unit tests for MCP hook sender response parsing."""

import json
import os
import threading
import time

import pytest

from teleclaude.hooks.utils.mcp_send import _read_json_response


def _write_lines(fd: int, lines: list[str], delay_s: float = 0.0) -> None:
    with os.fdopen(fd, "w") as writer:
        for line in lines:
            writer.write(line + "\n")
            writer.flush()
            if delay_s:
                time.sleep(delay_s)


def test_read_json_response_skips_notifications() -> None:
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "r")

    lines = [
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}),
    ]
    thread = threading.Thread(target=_write_lines, args=(write_fd, lines), daemon=True)
    thread.start()

    response = _read_json_response(reader, timeout_s=1.0, expected_id=1)
    assert response.get("id") == 1

    thread.join(timeout=1)
    reader.close()


def test_read_json_response_rejects_unexpected_id() -> None:
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "r")

    lines = [json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"ok": True}})]
    thread = threading.Thread(target=_write_lines, args=(write_fd, lines), daemon=True)
    thread.start()

    with pytest.raises(RuntimeError):
        _read_json_response(reader, timeout_s=1.0, expected_id=1)

    thread.join(timeout=1)
    reader.close()
