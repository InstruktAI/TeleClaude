"""Tests for the agent hook installation helper."""

import json
from pathlib import Path

from scripts import install_hooks


def test_merge_hooks_replaces_existing_hook_definition():
    """Existing hooks for the same event are replaced by the new definition (deduped by command)."""
    existing_hooks = {
        "SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "/tmp/new-hook"}]}],
    }

    new_hooks = {
        "SessionStart": {
            "type": "command",
            "command": "/tmp/new-hook",
        }
    }

    merged = install_hooks.merge_hooks(existing_hooks, new_hooks)

    assert "SessionStart" in merged
    block = merged["SessionStart"][0]
    assert block["matcher"] == "*"
    # Should deduplicate - only one hook with same command
    assert len(block["hooks"]) == 1
    assert block["hooks"][0]["command"] == "/tmp/new-hook"


def test_configure_claude_writes_hook_file(tmp_path, monkeypatch):
    """Claude hook configuration writes to ~/.claude/settings.json."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_root = Path(__file__).resolve().parents[2]

    install_hooks.configure_claude(repo_root)

    claude_config = tmp_path / ".claude" / "settings.json"
    assert claude_config.exists()

    data = json.loads(claude_config.read_text())
    assert "hooks" in data
    assert "SessionStart" in data["hooks"]
    hooks_block = data["hooks"]["SessionStart"][0]
    assert hooks_block["matcher"] == "*"
    # Claude hooks only have type and command (no name/description)
    hook = hooks_block["hooks"][0]
    assert hook["type"] == "command"
    assert "receiver_claude.py session_start" in hook["command"]
