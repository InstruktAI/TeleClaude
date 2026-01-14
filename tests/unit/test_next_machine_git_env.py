"""Unit tests for git hook environment helpers."""

import os

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.next_machine import build_git_hook_env


def test_build_git_hook_env_prepends_venv_bin() -> None:
    """Test that build_git_hook_env prepends the venv bin directory."""
    env = {"PATH": "/usr/local/bin:/usr/bin"}
    result = build_git_hook_env("/tmp/project", env)
    parts = result["PATH"].split(os.pathsep)

    assert parts[0] == "/tmp/project/.venv/bin"
    assert result["VIRTUAL_ENV"] == "/tmp/project/.venv"


def test_build_git_hook_env_dedupes_venv_bin() -> None:
    """Test that build_git_hook_env keeps only one venv bin entry."""
    env = {"PATH": "/usr/bin:/tmp/project/.venv/bin:/bin"}
    result = build_git_hook_env("/tmp/project", env)
    parts = result["PATH"].split(os.pathsep)

    assert parts[0] == "/tmp/project/.venv/bin"
    assert parts.count("/tmp/project/.venv/bin") == 1
