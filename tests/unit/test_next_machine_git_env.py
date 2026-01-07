"""Unit tests for git hook environment helpers."""

import os

from teleclaude.core.next_machine import build_git_hook_env


def test_build_git_hook_env_prepends_venv_bin() -> None:
    env = {"PATH": "/usr/local/bin:/usr/bin"}
    result = build_git_hook_env("/tmp/project", env)
    parts = result["PATH"].split(os.pathsep)

    assert parts[0] == "/tmp/project/.venv/bin"
    assert result["VIRTUAL_ENV"] == "/tmp/project/.venv"


def test_build_git_hook_env_dedupes_venv_bin() -> None:
    env = {"PATH": "/usr/bin:/tmp/project/.venv/bin:/bin"}
    result = build_git_hook_env("/tmp/project", env)
    parts = result["PATH"].split(os.pathsep)

    assert parts[0] == "/tmp/project/.venv/bin"
    assert parts.count("/tmp/project/.venv/bin") == 1
