"""Unit tests for mcp-wrapper tool cache refresh."""

from __future__ import annotations

import json
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_wrapper_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_WRAPPER_LOG_LEVEL", "CRITICAL")
    wrapper_path = Path(__file__).resolve().parents[2] / "bin" / "mcp-wrapper.py"
    spec = spec_from_file_location("teleclaude_test_mcp_wrapper_refresh", wrapper_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_refresh_tool_cache_if_needed_updates_on_mtime_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that tool cache refresh detects file mtime changes and reloads."""
    cache_path = tmp_path / "mcp-tools-cache.json"
    monkeypatch.setenv("MCP_WRAPPER_TOOL_CACHE_PATH", str(cache_path))
    wrapper = _load_wrapper_module(monkeypatch)
    wrapper._impl.TOOL_CACHE_PATH = cache_path
    wrapper._impl._TOOL_CACHE_MTIME = None
    wrapper._impl.TOOL_LIST_CACHE = None

    tools_v1 = [
        {
            "name": "teleclaude__one",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    cache_path.write_text(json.dumps(tools_v1), encoding="utf-8")

    wrapper.refresh_tool_cache_if_needed(force=True)
    assert wrapper._impl.TOOL_LIST_CACHE
    assert wrapper._impl.TOOL_LIST_CACHE[0]["name"] == "teleclaude__one"

    time.sleep(0.01)
    tools_v2 = [
        {
            "name": "teleclaude__two",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    cache_path.write_text(json.dumps(tools_v2), encoding="utf-8")

    wrapper.refresh_tool_cache_if_needed()
    assert wrapper._impl.TOOL_LIST_CACHE
    assert wrapper._impl.TOOL_LIST_CACHE[0]["name"] == "teleclaude__two"
