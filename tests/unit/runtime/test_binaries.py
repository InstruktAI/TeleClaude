"""Characterization tests for teleclaude.runtime.binaries."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.runtime import binaries


def test_resolve_tmux_binary_uses_macos_launcher_on_darwin() -> None:
    with patch("teleclaude.runtime.binaries._is_macos", return_value=True):
        assert binaries.resolve_tmux_binary() == str(binaries._MACOS_TMUX_BINARY)


def test_resolve_tmux_binary_uses_tmux_on_non_macos_platforms() -> None:
    with patch("teleclaude.runtime.binaries._is_macos", return_value=False):
        assert binaries.resolve_tmux_binary() == "tmux"


def test_resolve_agent_binary_normalizes_input_for_unix_binaries() -> None:
    with patch("teleclaude.runtime.binaries._is_macos", return_value=False):
        assert binaries.resolve_agent_binary("  CoDeX  ") == "codex"


def test_resolve_agent_binary_returns_macos_launcher_for_known_agents() -> None:
    with patch("teleclaude.runtime.binaries._is_macos", return_value=True):
        assert binaries.resolve_agent_binary("  gemini ") == str(binaries._MACOS_AGENT_BINARIES["gemini"])


def test_resolve_agent_binary_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        binaries.resolve_agent_binary("unknown")
