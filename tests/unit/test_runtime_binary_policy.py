"""Runtime binary policy and config guardrail tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from teleclaude.runtime.binaries import resolve_agent_binary, resolve_tmux_binary


def _load_config_module(config_py: Path) -> object:
    module_name = "teleclaude_config_test_runtime_binary_policy"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, config_py)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_binary_resolution_platform_policy() -> None:
    """Runtime resolver should enforce platform policy for all agent/tmux binaries."""
    if sys.platform == "darwin":
        assert resolve_tmux_binary().endswith("/Applications/TmuxLauncher.app/Contents/MacOS/tmux-launcher")
        assert resolve_agent_binary("claude").endswith("/Applications/ClaudeLauncher.app/Contents/MacOS/claude-launcher")
        assert resolve_agent_binary("gemini").endswith("/Applications/GeminiLauncher.app/Contents/MacOS/gemini-launcher")
        assert resolve_agent_binary("codex").endswith("/Applications/CodexLauncher.app/Contents/MacOS/codex-launcher")
    else:
        assert resolve_tmux_binary() == "tmux"
        assert resolve_agent_binary("claude") == "claude"
        assert resolve_agent_binary("gemini") == "gemini"
        assert resolve_agent_binary("codex") == "codex"


def test_config_rejects_legacy_agents_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config.yml must reject legacy agent binary configuration keys."""
    repo_root = Path(__file__).resolve().parents[2]
    config_py = repo_root / "teleclaude" / "config" / "__init__.py"

    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "agents:\n"
        "  claude:\n"
        "    binary: /tmp/claude\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("TELECLAUDE_ENV_PATH", str(env_path))
    monkeypatch.delenv("TELECLAUDE_DB_PATH", raising=False)

    with pytest.raises(ValueError, match="disallowed runtime keys: agents"):
        _load_config_module(config_py)


def test_config_rejects_legacy_tmux_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config.yml must reject legacy tmux binary configuration key."""
    repo_root = Path(__file__).resolve().parents[2]
    config_py = repo_root / "teleclaude" / "config" / "__init__.py"

    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "computer:\n"
        "  tmux_binary: /tmp/tmux\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("TELECLAUDE_ENV_PATH", str(env_path))
    monkeypatch.delenv("TELECLAUDE_DB_PATH", raising=False)

    with pytest.raises(ValueError, match="disallowed runtime keys: computer\\.tmux_binary"):
        _load_config_module(config_py)
