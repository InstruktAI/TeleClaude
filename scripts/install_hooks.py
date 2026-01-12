#!/usr/bin/env python3
"""Install/Update agent hooks configuration.

This script configures AI agents (Gemini, Claude, etc.) to use TeleClaude hooks.
It idempotently merges hook definitions into the agent's settings file.
The hooks point to the receiver scripts within this repository.
"""

import json
import os
import re
import shlex
import tomllib
from pathlib import Path
from typing import Any, Dict


def _extract_receiver_script(command: str) -> str | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    for part in parts:
        if part.endswith(".py") and "receiver" in part:
            # Normalize legacy receiver_claude/receiver_gemini to receiver.py family
            if (
                part.endswith("receiver.py")
                or part.endswith("receiver_claude.py")
                or part.endswith("receiver_gemini.py")
            ):
                return "receiver"
            return part
    return None


def merge_hooks(existing_hooks: Dict[str, Any], new_hooks: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently merge new hooks into existing hooks configuration.

    Deduplicates by receiver script path so old hook entries are replaced.
    """
    merged = existing_hooks.copy()

    for event, hook_def in new_hooks.items():
        event_hooks = merged.get(event, [])

        # Structure: [{"matcher": "*", "hooks": [...]}]
        # We target the "*" matcher block or create one

        target_block = None
        for block in event_hooks:
            if block.get("matcher") == "*":
                target_block = block
                break

        if not target_block:
            target_block = {"matcher": "*", "hooks": []}
            event_hooks.append(target_block)

        # Update specific hook within the block
        hooks_list = target_block.get("hooks", [])

        new_command = hook_def.get("command", "")
        new_receiver = _extract_receiver_script(new_command)

        filtered_hooks = []
        for h in hooks_list:
            cmd = h.get("command")
            if not cmd:
                filtered_hooks.append(h)
                continue
            if cmd == new_command:
                continue
            if new_receiver:
                existing_receiver = _extract_receiver_script(cmd)
                if existing_receiver == new_receiver:
                    continue
            filtered_hooks.append(h)

        # Add new hook definition
        filtered_hooks.append(hook_def)
        hooks_list = filtered_hooks
        target_block["hooks"] = hooks_list

        merged[event] = event_hooks

    return merged


def _resolve_hook_python(repo_root: Path) -> Path:
    override = os.getenv("TELECLAUDE_HOOK_PYTHON")
    if override:
        return Path(override).expanduser()

    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        raise FileNotFoundError(f"Expected TeleClaude venv python at {venv_python}")
    return venv_python


def _claude_hook_map(python_exe: Path, receiver_script: Path) -> Dict[str, Dict[str, str]]:
    """Return TeleClaude hook definitions for Claude Code.

    Claude valid events: PreToolUse, PostToolUse, PostToolUseFailure, Notification,
    UserPromptSubmit, SessionStart, SessionEnd, Stop, SubagentStart, SubagentStop,
    PreCompact, PermissionRequest

    Note: Claude hooks only use 'type' and 'command' - no 'name' or 'description'.
    """
    return {
        "SessionStart": {
            "type": "command",
            "command": f"{python_exe} {receiver_script} --agent claude session_start",
        },
        "Stop": {
            "type": "command",
            "command": f"{python_exe} {receiver_script} --agent claude stop",
        },
    }


def _prune_claude_hooks(existing_hooks: Dict[str, Any]) -> Dict[str, Any]:
    """Remove TeleClaude receiver hooks from unused Claude events.

    Keep TeleClaude hooks only for SessionStart and Stop.
    Preserve all non-TeleClaude hooks.
    """
    allowed_events = {"SessionStart", "Stop"}
    pruned: Dict[str, Any] = {}

    for event, blocks in existing_hooks.items():
        if not isinstance(blocks, list):
            pruned[event] = blocks
            continue

        new_blocks = []
        for block in blocks:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue

            hooks_list = block.get("hooks", [])
            if not isinstance(hooks_list, list):
                new_blocks.append(block)
                continue

            if event in allowed_events:
                filtered_hooks = hooks_list
            else:
                filtered_hooks = []
                for hook in hooks_list:
                    if not isinstance(hook, dict):
                        filtered_hooks.append(hook)
                        continue
                    cmd = hook.get("command", "")
                    if _extract_receiver_script(cmd) == "receiver":
                        continue
                    filtered_hooks.append(hook)

            if filtered_hooks:
                updated_block = block.copy()
                updated_block["hooks"] = filtered_hooks
                new_blocks.append(updated_block)

        if new_blocks:
            pruned[event] = new_blocks

    return pruned


def _gemini_hook_map(python_exe: Path, receiver_script: Path) -> Dict[str, Dict[str, str]]:
    """Return TeleClaude hook definitions for Gemini CLI.

    Gemini uses AfterAgent for turn completion (equivalent to Claude's Stop hook).
    Note: BeforeUserInput does NOT exist in Gemini CLI.
    """
    hooks: Dict[str, Dict[str, str]] = {
        "SessionStart": {
            "name": "teleclaude-session-start",
            "type": "command",
            "command": f"{python_exe} {receiver_script} --agent gemini session_start",
            "description": "Notify TeleClaude of session start",
        },
        # AfterAgent fires when agent loop ends = turn completion = stop event
        "AfterAgent": {
            "name": "teleclaude-stop",
            "type": "command",
            "command": f"{python_exe} {receiver_script} --agent gemini stop",
            "description": "Notify TeleClaude of turn completion",
        },
    }

    # Note: We don't need intermediate hooks (BeforeAgent, BeforeModel, etc.)
    # The _discover_transcript_path fallback in gemini.py adapter resolves
    # transcript_path from cwd + session_id, so we only need the core events.

    return hooks


def _prune_gemini_hooks(existing_hooks: Dict[str, Any]) -> Dict[str, Any]:
    """Remove TeleClaude receiver hooks from unused Gemini events.

    Keep TeleClaude hooks only for SessionStart and AfterAgent.
    Preserve all non-TeleClaude hooks.
    """
    allowed_events = {"SessionStart", "AfterAgent"}
    pruned: Dict[str, Any] = {}

    for event, blocks in existing_hooks.items():
        if not isinstance(blocks, list):
            pruned[event] = blocks
            continue

        new_blocks = []
        for block in blocks:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue

            hooks_list = block.get("hooks", [])
            if not isinstance(hooks_list, list):
                new_blocks.append(block)
                continue

            if event in allowed_events:
                filtered_hooks = hooks_list
            else:
                filtered_hooks = []
                for hook in hooks_list:
                    if not isinstance(hook, dict):
                        filtered_hooks.append(hook)
                        continue
                    cmd = hook.get("command", "")
                    if _extract_receiver_script(cmd) == "receiver":
                        continue
                    filtered_hooks.append(hook)

            if filtered_hooks:
                updated_block = block.copy()
                updated_block["hooks"] = filtered_hooks
                new_blocks.append(updated_block)

        if new_blocks:
            pruned[event] = new_blocks

    return pruned


def configure_gemini(repo_root: Path) -> None:
    """Configure Gemini CLI hooks."""
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver.py"
    if not receiver_script.exists():
        print(f"Warning: Gemini receiver not found at {receiver_script}")
        return

    # Ensure executable
    os.chmod(receiver_script, 0o755)

    settings_path = Path.home() / ".gemini" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load Gemini settings: {e}")

    # Define hooks (Gemini-specific event names)
    python_exe = _resolve_hook_python(repo_root)
    hooks_map = _gemini_hook_map(python_exe, receiver_script)

    # Prune TeleClaude hooks from events we do not use.
    existing_hooks = settings.get("hooks", {})
    settings["hooks"] = _prune_gemini_hooks(existing_hooks)

    # Merge
    current_hooks = settings.get("hooks", {})
    settings["hooks"] = merge_hooks(current_hooks, hooks_map)

    # Ensure hooks are enabled (Gemini requires explicit flag).
    tools_cfg = settings.get("tools")
    if not isinstance(tools_cfg, dict):
        tools_cfg = {}
    tools_cfg["enableHooks"] = True
    settings["tools"] = tools_cfg

    # Save
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"Gemini hooks configured in {settings_path}")


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver.py"
    if not receiver_script.exists():
        print(f"Warning: Claude receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)

    # Claude Code hooks go in ~/.claude/settings.json (NOT ~/.claude.json)
    settings_path = Path.home() / ".claude" / "settings.json"

    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load Claude settings: {e}")

    # Define hooks (Claude-specific event names)
    python_exe = _resolve_hook_python(repo_root)
    hooks_map = _claude_hook_map(python_exe, receiver_script)

    current_hooks = settings.get("hooks", {})
    pruned_hooks = _prune_claude_hooks(current_hooks)
    settings["hooks"] = merge_hooks(pruned_hooks, hooks_map)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"Claude hooks configured in {settings_path}")


def configure_codex(repo_root: Path) -> None:
    """Configure Codex CLI notify hook.

    Codex uses TOML config at ~/.codex/config.toml with a simple `notify` key
    that takes an array of command parts. Unlike Claude/Gemini which use JSON
    with nested hook structures, Codex only supports one hook event type:
    `agent-turn-complete` which maps to our internal "stop" event.
    """
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver.py"
    if not receiver_script.exists():
        print(f"Warning: Codex receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)

    config_path = Path.home() / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    python_exe = _resolve_hook_python(repo_root)
    notify_value = [str(python_exe), str(receiver_script), "--agent", "codex"]

    if config_path.exists():
        content = config_path.read_text()
        try:
            config = tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            print(f"Warning: Failed to parse Codex config: {e}")
            return

        existing_notify = config.get("notify")
        skip_notify_update = False
        if existing_notify == notify_value:
            print(f"Codex notify hook already configured in {config_path}")
            skip_notify_update = True

        if not skip_notify_update:
            # Update or add notify line using text manipulation to preserve formatting
            notify_line = f'notify = {json.dumps(notify_value)}'
            if "notify" in config:
                # Check if existing notify is our hook (contains receiver.py and --agent codex)
                is_our_hook = (
                    isinstance(existing_notify, list)
                    and len(existing_notify) >= 4
                    and "receiver.py" in str(existing_notify[1])
                    and existing_notify[2:4] == ["--agent", "codex"]
                )
                if not is_our_hook:
                    print(f"Warning: Existing notify hook in {config_path} is not ours, skipping")
                    print(f"  Existing: {existing_notify}")
                    skip_notify_update = True
                else:
                    # Replace our existing notify line with updated paths
                    content = re.sub(
                        r'^notify\s*=\s*\[.*?\]',
                        notify_line,
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
            if not skip_notify_update and "notify" not in config:
                # Add notify after any comments at the top, before first section
                first_section = re.search(r'^\[', content, re.MULTILINE)
                if first_section:
                    insert_pos = first_section.start()
                    content = content[:insert_pos] + notify_line + "\n\n" + content[insert_pos:]
                else:
                    content = content.rstrip() + "\n\n" + notify_line + "\n"
    else:
        # Create new config with just the notify hook
        notify_line = f'notify = {json.dumps(notify_value)}'
        content = f"# Codex CLI configuration\n\n{notify_line}\n"

    content = ensure_codex_mcp_config(content, repo_root)
    config_path.write_text(content)
    print(f"Codex notify hook configured in {config_path}")


def ensure_codex_mcp_config(content: str, repo_root: Path) -> str:
    """Ensure Codex MCP server config points at the repo venv wrapper."""
    venv_python = repo_root / ".venv" / "bin" / "python"
    wrapper_path = repo_root / "bin" / "mcp-wrapper.py"

    desired_block = (
        "# TeleClaude MCP Server\n"
        "[mcp_servers.teleclaude]\n"
        "type = \"stdio\"\n"
        f"command = \"{venv_python}\"\n"
        f"args = [\"{wrapper_path}\"]\n"
    )

    section_name = "mcp_servers.teleclaude"
    section_pattern = re.compile(
        rf"(?ms)^(?:# TeleClaude MCP Server\n)?\[{re.escape(section_name)}\]\n"
        r"(?:^(?!\[).*$\n?)*"
    )
    content = section_pattern.sub("", content)
    content = content.rstrip() + "\n\n" + desired_block
    return content


def main() -> None:
    # Repo root is parent of scripts/ dir
    repo_root = Path(__file__).parent.parent.resolve()
    print(f"Configuring hooks from repo: {repo_root}")

    configure_claude(repo_root)
    configure_gemini(repo_root)
    configure_codex(repo_root)


if __name__ == "__main__":
    main()
