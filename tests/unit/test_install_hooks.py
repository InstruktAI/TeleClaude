"""Tests for the agent hook installation helper."""

import json
import tomllib
from pathlib import Path

from teleclaude.install import install_hooks


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
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
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
    command = hook["command"]
    if isinstance(command, list):
        command_text = " ".join(command)
    else:
        command_text = command
    assert 'receiver.py --agent claude --cwd "$PWD" session_start' in command_text


def test_configure_gemini_writes_only_required_hook_events(tmp_path, monkeypatch):
    """Gemini hook configuration should only install start/user_prompt_submit/agent_stop events."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    install_hooks.configure_gemini(repo_root)

    gemini_config = tmp_path / ".gemini" / "settings.json"
    assert gemini_config.exists()

    data = json.loads(gemini_config.read_text())
    hooks = data["hooks"]
    assert set(hooks.keys()) == {"enabled", "SessionStart", "UserPromptSubmit", "AfterAgent"}
    assert hooks["enabled"] is True

    prompt_hook = hooks["UserPromptSubmit"][0]["hooks"][0]
    command = prompt_hook["command"]
    if isinstance(command, list):
        command_text = " ".join(command)
    else:
        command_text = command
    assert 'receiver.py --agent gemini --cwd "$PWD" user_prompt_submit' in command_text


def test_configure_codex_writes_notify_hook(tmp_path, monkeypatch):
    """Codex hook configuration writes notify array to ~/.codex/config.toml."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    install_hooks.configure_codex(repo_root)

    codex_config = tmp_path / ".codex" / "config.toml"
    assert codex_config.exists()

    data = tomllib.loads(codex_config.read_text())
    assert "notify" in data
    notify = data["notify"]
    assert isinstance(notify, list)
    assert len(notify) == 4
    assert notify[0] == "/bin/bash"
    assert notify[1] == "-lc"
    assert "receiver.py" in notify[2]
    assert "--agent codex" in notify[2]
    assert ' --cwd "$PWD" "$1"' in notify[2]
    assert notify[3] == "hook"
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]


def test_configure_codex_preserves_existing_config(tmp_path, monkeypatch):
    """Codex hook configuration preserves existing settings in config.toml."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    # Create existing config with other settings
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    codex_config.write_text('model = "gpt-4"\nsandbox_mode = "safe"\n')

    install_hooks.configure_codex(repo_root)

    data = tomllib.loads(codex_config.read_text())
    # Existing settings preserved
    assert data["model"] == "gpt-4"
    assert data["sandbox_mode"] == "safe"
    # New notify hook added
    assert "notify" in data
    assert "receiver.py" in data["notify"][2]
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]


def test_configure_codex_is_idempotent(tmp_path, monkeypatch):
    """Running configure_codex twice produces identical results without corruption."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    # Create existing config with settings and a comment
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    codex_config.write_text('# My config\nmodel = "gpt-4"\n\n[mcp_servers.test]\ntype = "stdio"\n')

    # First run
    install_hooks.configure_codex(repo_root)
    content_after_first = codex_config.read_text()

    # Second run
    install_hooks.configure_codex(repo_root)
    content_after_second = codex_config.read_text()
    data_after_second = tomllib.loads(content_after_second)

    # Content should be identical after second run
    assert content_after_first == content_after_second

    # Data integrity checks
    assert data_after_second["model"] == "gpt-4"
    assert data_after_second["mcp_servers"]["test"]["type"] == "stdio"
    assert "notify" in data_after_second
    assert len(data_after_second["notify"]) == 4
    assert data_after_second["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data_after_second["mcp_servers"]["teleclaude"]["args"][0]


def test_configure_codex_updates_our_hook_when_paths_change(tmp_path, monkeypatch):
    """Our notify hook is updated when python path or receiver path changes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    # Create config with our hook but old paths (simulating repo move or venv change)
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    old_hook = '["/old/venv/python", "/old/path/teleclaude/hooks/receiver.py", "--agent", "codex"]'
    codex_config.write_text(f'model = "gpt-4"\nnotify = {old_hook}\n')

    install_hooks.configure_codex(repo_root)

    data = tomllib.loads(codex_config.read_text())
    # Our hook updated to new paths
    assert data["notify"][0] == "/bin/bash"
    assert data["notify"][1] == "-lc"
    assert str(hook_python) in data["notify"][2]
    assert "receiver.py" in data["notify"][2]
    assert "--agent codex" in data["notify"][2]
    assert data["notify"][3] == "hook"
    # Old paths gone
    assert "/old/venv/python" not in str(data["notify"])
    assert "/old/path/" not in str(data["notify"])
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]


def test_configure_codex_skips_foreign_notify_hook(tmp_path, monkeypatch, capsys):
    """Foreign notify hook (not ours) is not replaced - we skip with a warning."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    # Create config with someone else's notify hook
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    foreign_hook = '["/usr/bin/python", "/their/custom/script.py", "--some", "args"]'
    codex_config.write_text(f'model = "gpt-4"\nnotify = {foreign_hook}\n')
    install_hooks.configure_codex(repo_root)

    data = tomllib.loads(codex_config.read_text())
    assert data["notify"] == ["/usr/bin/python", "/their/custom/script.py", "--some", "args"]
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]

    # Warning should be printed
    captured = capsys.readouterr()
    assert "not ours" in captured.out


def test_configure_codex_replaces_existing_mcp_block(tmp_path, monkeypatch):
    """Existing MCP block is replaced with the repo venv config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    codex_config.write_text(
        'model = "gpt-4"\n\n'
        "[mcp_servers.teleclaude]\n"
        'type = "stdio"\n'
        'command = "python3"\n'
        'args = ["/old/path/mcp-wrapper.py"]\n'
    )

    install_hooks.configure_codex(repo_root)

    data = tomllib.loads(codex_config.read_text())
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert str(repo_root / ".venv" / "bin" / "python") == data["mcp_servers"]["teleclaude"]["command"]
    assert str(repo_root / "bin" / "mcp-wrapper.py") in data["mcp_servers"]["teleclaude"]["args"][0]
