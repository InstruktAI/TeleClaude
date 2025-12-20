#!/usr/bin/env python3
"""Install/Update agent hooks configuration.

This script configures AI agents (Gemini, Claude, etc.) to use TeleClaude hooks.
It idempotently merges hook definitions into the agent's settings file.
The hooks point to the receiver scripts within this repository.
"""

import json
import os
import shlex
from pathlib import Path
from typing import Any, Dict


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

        def _extract_receiver_script(command: str) -> str | None:
            try:
                parts = shlex.split(command)
            except ValueError:
                return None
            for part in parts:
                if part.endswith(".py") and "receiver_" in part:
                    return part
            return None

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
            "command": f"{python_exe} {receiver_script} session_start",
        },
        "Notification": {
            "type": "command",
            "command": f"{python_exe} {receiver_script} notification",
        },
        "Stop": {
            "type": "command",
            "command": f"{python_exe} {receiver_script} stop",
        },
    }


def _gemini_hook_map(python_exe: Path, receiver_script: Path) -> Dict[str, Dict[str, str]]:
    """Return TeleClaude hook definitions for Gemini CLI.

    Gemini uses AfterModel for turn completion (not Stop like Claude).
    """
    return {
        "SessionStart": {
            "name": "teleclaude-session-start",
            "type": "command",
            "command": f"{python_exe} {receiver_script} session_start",
            "description": "Notify TeleClaude of session start",
        },
        "Notification": {
            "name": "teleclaude-notification",
            "type": "command",
            "command": f"{python_exe} {receiver_script} notification",
            "description": "Notify TeleClaude of user input request",
        },
        "AfterModel": {
            "name": "teleclaude-stop",
            "type": "command",
            "command": f"{python_exe} {receiver_script} stop",
            "description": "Notify TeleClaude of turn completion",
        },
    }


def configure_gemini(repo_root: Path) -> None:
    """Configure Gemini CLI hooks."""
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver_gemini.py"
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

    # Merge
    current_hooks = settings.get("hooks", {})
    settings["hooks"] = merge_hooks(current_hooks, hooks_map)

    # Save
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"Gemini hooks configured in {settings_path}")


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver_claude.py"
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
    settings["hooks"] = merge_hooks(current_hooks, hooks_map)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"Claude hooks configured in {settings_path}")


def main() -> None:
    # Repo root is parent of scripts/ dir
    repo_root = Path(__file__).parent.parent.resolve()
    print(f"Configuring hooks from repo: {repo_root}")

    configure_claude(repo_root)
    configure_gemini(repo_root)
    # Add configure_claude(repo_root) here in future


if __name__ == "__main__":
    main()
