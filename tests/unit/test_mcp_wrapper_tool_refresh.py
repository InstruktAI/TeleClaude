"""Unit tests for mcp-wrapper tool cache refresh."""

from __future__ import annotations

import os
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
    wrapper = _load_wrapper_module(monkeypatch)

    fake_server = tmp_path / "mcp_server.py"
    fake_server.write_text('Tool(name="teleclaude__one")\\n', encoding="utf-8")
    os.utime(fake_server, None)

    monkeypatch.setattr(wrapper, "_get_mcp_server_path", lambda: fake_server)
    wrapper.refresh_tool_cache_if_needed(force=True)
    assert "teleclaude__one" in wrapper.TOOL_NAMES

    time.sleep(0.01)
    fake_server.write_text('Tool(name="teleclaude__two")\\n', encoding="utf-8")
    os.utime(fake_server, None)

    wrapper.refresh_tool_cache_if_needed()
    assert "teleclaude__two" in wrapper.TOOL_NAMES
