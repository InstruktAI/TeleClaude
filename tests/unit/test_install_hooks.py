"""Tests for the agent hook installation helper."""

import json
import tomllib
from pathlib import Path

from teleclaude.install import install_hooks


def test_resolve_main_repo_root_from_worktree(tmp_path):
    """Worktree .git file is followed to find the main repo root."""
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    (main_repo / ".git").mkdir()
    (main_repo / ".git" / "worktrees" / "feature-x").mkdir(parents=True)

    worktree = tmp_path / "trees" / "feature-x"
    worktree.mkdir(parents=True)
    gitdir = main_repo / ".git" / "worktrees" / "feature-x"
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

    assert install_hooks.resolve_main_repo_root(worktree) == main_repo


def test_resolve_main_repo_root_from_main_repo(tmp_path):
    """Main repo .git directory is recognized directly."""
    main_repo = tmp_path / "repo"
    main_repo.mkdir()
    (main_repo / ".git").mkdir()

    assert install_hooks.resolve_main_repo_root(main_repo) == main_repo


def test_resolve_main_repo_root_relative_gitdir(tmp_path):
    """Relative gitdir paths in .git file are resolved correctly."""
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    (main_repo / ".git").mkdir()
    (main_repo / ".git" / "worktrees" / "feat").mkdir(parents=True)

    worktree = main_repo / "trees" / "feat"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../../.git/worktrees/feat\n")

    assert install_hooks.resolve_main_repo_root(worktree) == main_repo


def test_resolve_main_repo_root_fallback_no_git(tmp_path):
    """Returns start path when no .git is found."""
    bare_dir = tmp_path / "no-git"
    bare_dir.mkdir()

    assert install_hooks.resolve_main_repo_root(bare_dir) == bare_dir


def test_configure_claude_never_embeds_worktree_path(tmp_path, monkeypatch):
    """Hook commands always point to main repo receiver, never a worktree."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Create a dummy "main repo" that doesn't have "trees/" in its path
    # even if our current worktree does.
    fake_main_repo = tmp_path / "teleclaude-main"
    fake_main_repo.mkdir()
    (fake_main_repo / "teleclaude" / "hooks").mkdir(parents=True)
    (fake_main_repo / "teleclaude" / "hooks" / "receiver.py").touch()

    # Force configure_claude to use our fake main repo instead of discovering the current worktree
    monkeypatch.setattr(install_hooks, "resolve_main_repo_root", lambda start=None: fake_main_repo)

    install_hooks.configure_claude(fake_main_repo)

    claude_config = tmp_path / ".claude" / "settings.json"
    data = json.loads(claude_config.read_text())
    hook_cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    assert "trees/" not in hook_cmd
    assert str(fake_main_repo / "teleclaude" / "hooks" / "receiver.py") in hook_cmd


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
    assert "PreCompact" not in data["hooks"]
    assert "SessionEnd" not in data["hooks"]
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
    """Gemini hook configuration should only install receiver-handled events."""
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
    assert set(hooks.keys()) == {
        "enabled",
        "SessionStart",
        "BeforeAgent",
        "AfterAgent",
        "BeforeTool",
        "AfterTool",
        "Notification",
    }
    assert hooks["enabled"] == ["*"]

    prompt_hook = hooks["BeforeAgent"][0]["hooks"][0]
    command = prompt_hook["command"]
    if isinstance(command, list):
        command_text = " ".join(command)
    else:
        command_text = command
    assert 'receiver.py --agent gemini --cwd "$PWD" user_prompt_submit' in command_text

    before_tool_hook = hooks["BeforeTool"][0]["hooks"][0]
    before_tool_command = before_tool_hook["command"]
    if isinstance(before_tool_command, list):
        before_tool_command_text = " ".join(before_tool_command)
    else:
        before_tool_command_text = before_tool_command
    assert 'receiver.py --agent gemini --cwd "$PWD" tool_use' in before_tool_command_text

    after_tool_hook = hooks["AfterTool"][0]["hooks"][0]
    after_tool_command = after_tool_hook["command"]
    if isinstance(after_tool_command, list):
        after_tool_command_text = " ".join(after_tool_command)
    else:
        after_tool_command_text = after_tool_command
    assert 'receiver.py --agent gemini --cwd "$PWD" tool_done' in after_tool_command_text


def test_configure_gemini_drops_stale_unhandled_hook_keys(tmp_path, monkeypatch):
    """Gemini installer removes stale unhandled hook keys left from old configs."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hook_python = tmp_path / "python"
    hook_python.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("TELECLAUDE_HOOK_PYTHON", str(hook_python))
    repo_root = Path(__file__).resolve().parents[2]

    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir(parents=True)
    gemini_config = gemini_dir / "settings.json"
    gemini_config.write_text(
        json.dumps(
            {
                "hooks": {
                    "enabled": ["*"],
                    "BeforeModel": None,
                    "BeforeToolSelection": None,
                    "PreCompress": None,
                    "SessionEnd": None,
                }
            }
        )
    )

    install_hooks.configure_gemini(repo_root)

    data = json.loads(gemini_config.read_text())
    hooks = data["hooks"]
    assert "BeforeModel" not in hooks
    assert "BeforeToolSelection" not in hooks
    assert "PreCompress" not in hooks
    assert "SessionEnd" not in hooks


def test_configure_codex_writes_notify_hook(tmp_path, monkeypatch):
    """Codex hook configuration writes notify array to ~/.codex/config.toml."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_root = Path(__file__).resolve().parents[2]

    install_hooks.configure_codex(repo_root)

    codex_config = tmp_path / ".codex" / "config.toml"
    assert codex_config.exists()

    data = tomllib.loads(codex_config.read_text())
    assert "notify" in data
    notify = data["notify"]
    assert isinstance(notify, list)
    assert len(notify) == 3
    assert notify[0].endswith("/teleclaude/hooks/receiver.py")
    assert notify[1] == install_hooks.AGENT_FLAG
    assert notify[2] == install_hooks.CODEX_AGENT
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][-1]


def test_configure_codex_preserves_existing_config(tmp_path, monkeypatch):
    """Codex hook configuration preserves existing settings in config.toml."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_root = Path(__file__).resolve().parents[2]

    # Create existing config with other settings
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    codex_config.write_text('model = "gpt-4"\nsandbox_mode = "safe"\n')

    install_hooks.configure_codex(repo_root)

    data = tomllib.loads(codex_config.read_text())
    # Non-override settings preserved
    assert data["model"] == "gpt-4"
    # Override settings applied (settings/codex.json wins over existing values)
    assert data["sandbox_mode"] == "danger-full-access"
    assert data["approval_policy"] == "never"
    # New notify hook added
    assert "notify" in data
    assert data["notify"][0].endswith("/teleclaude/hooks/receiver.py")
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][-1]


def test_configure_codex_is_idempotent(tmp_path, monkeypatch):
    """Running configure_codex twice produces identical results without corruption."""
    monkeypatch.setenv("HOME", str(tmp_path))
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
    assert len(data_after_second["notify"]) == 3
    assert data_after_second["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data_after_second["mcp_servers"]["teleclaude"]["args"][-1]


def test_configure_codex_updates_our_hook_when_paths_change(tmp_path, monkeypatch):
    """Our notify hook is updated when python path or receiver path changes."""
    monkeypatch.setenv("HOME", str(tmp_path))
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
    assert data["notify"][0].endswith("/teleclaude/hooks/receiver.py")
    assert data["notify"][1] == install_hooks.AGENT_FLAG
    assert data["notify"][2] == install_hooks.CODEX_AGENT
    # Old paths gone
    assert "/old/venv/python" not in str(data["notify"])
    assert "/old/path/" not in str(data["notify"])
    assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][-1]


def test_configure_codex_skips_foreign_notify_hook(tmp_path, monkeypatch, capsys):
    """Foreign notify hook (not ours) is not replaced - we skip with a warning."""
    monkeypatch.setenv("HOME", str(tmp_path))
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
    assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][-1]

    # Warning should be printed
    captured = capsys.readouterr()
    assert "not ours" in captured.out


def test_configure_codex_replaces_existing_mcp_block(tmp_path, monkeypatch):
    """Existing MCP block is replaced with the repo venv config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_root = Path(__file__).resolve().parents[2]
    main_repo = install_hooks.resolve_main_repo_root(repo_root)

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
    assert data["mcp_servers"]["teleclaude"]["command"] == "uv"
    assert data["mcp_servers"]["teleclaude"]["args"] == [
        "run",
        "--quiet",
        "--project",
        str(main_repo),
        str(main_repo / "bin" / "mcp-wrapper.py"),
    ]
    assert str(main_repo / "bin" / "mcp-wrapper.py") in data["mcp_servers"]["teleclaude"]["args"][-1]


def test_install_agent_wrapper_renders_canonical_root(tmp_path, monkeypatch):
    """Wrapper templates should render canonical root and install executable binaries."""
    monkeypatch.setenv("HOME", str(tmp_path))

    template_dir = tmp_path / "wrapper-templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "git").write_text(
        "#!/usr/bin/env bash\ncanonical={{CANONICAL_ROOT}}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(install_hooks, "WRAPPER_TEMPLATE_DIR", template_dir)

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    install_hooks.install_agent_wrapper(repo_root, "git")

    target = tmp_path / ".teleclaude" / "bin" / "git"
    assert target.exists()
    assert f"canonical={repo_root}" in target.read_text(encoding="utf-8")
    assert target.stat().st_mode & 0o111
