"""Unit tests for mcp-wrapper log throttling."""

from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_wrapper_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_WRAPPER_LOG_LEVEL", "CRITICAL")
    wrapper_path = Path(__file__).resolve().parents[2] / "bin" / "mcp-wrapper.py"
    spec = spec_from_file_location("teleclaude_test_mcp_wrapper_throttle", wrapper_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.mark.asyncio
async def test_log_throttled_suppresses_repeats(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()
    proxy._log_throttle_s = 10.0

    calls: list[tuple[int, str]] = []

    class _Logger:
        def log(self, level: int, msg: str, *args: object) -> None:
            calls.append((level, msg % args if args else msg))

        def debug(self, msg: str, *args: object) -> None:
            calls.append((10, (msg % args) if args else msg))

    monkeypatch.setattr(wrapper, "logger", _Logger())

    proxy._log_throttled("k", 30, "hello %s", "x")
    proxy._log_throttled("k", 30, "hello %s", "x")
    await asyncio.sleep(0)

    # First is logged at level 30, second is throttled to debug.
    assert calls[0][0] == 30
    assert calls[1][0] == 10
