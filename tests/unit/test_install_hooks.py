"""Tests for the agent hook installation helper."""

import json
from pathlib import Path

from scripts import install_hooks


def test_merge_hooks_replaces_existing_hook_definition():
    """Existing hooks for the same event are replaced by the new definition."""
    existing_hooks = {
        "SessionStart": [{"matcher": "*", "hooks": [{"name": "teleclaude-session-start", "command": "old"}]}],
    }

    new_hooks = {
        "SessionStart": {
            "name": "teleclaude-session-start",
            "type": "command",
            "command": "/tmp/new-hook",
            "description": "Notify TeleClaude of session start",
        }
    }

    merged = install_hooks.merge_hooks(existing_hooks, new_hooks)

    assert "SessionStart" in merged
    block = merged["SessionStart"][0]
    assert block["matcher"] == "*"
    assert len(block["hooks"]) == 1
    assert block["hooks"][0]["command"] == "/tmp/new-hook"


def test_configure_claude_writes_hook_file(tmp_path, monkeypatch):
    """Claude hook configuration writes to ~/.claude.json."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_root = Path(__file__).resolve().parents[2]

    install_hooks.configure_claude(repo_root)

    claude_config = tmp_path / ".claude.json"
    assert claude_config.exists()

    data = json.loads(claude_config.read_text())
    assert "hooks" in data
    assert "SessionStart" in data["hooks"]
    hooks_block = data["hooks"]["SessionStart"][0]
    assert hooks_block["matcher"] == "*"
    assert hooks_block["hooks"][0]["name"] == "teleclaude-session-start"
