#!/usr/bin/env python3
"""Install/Update agent hooks configuration.

This script configures AI agents (Gemini, Claude, etc.) to use TeleClaude hooks.
It idempotently merges hook definitions into the agent's settings file.
The hooks point to the receiver scripts within this repository.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict


def merge_hooks(existing_hooks: Dict[str, Any], new_hooks: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently merge new hooks into existing hooks configuration."""
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

        # Remove existing hook with same name to replace it
        hooks_list = [h for h in hooks_list if h.get("name") != hook_def["name"]]

        # Add new hook definition
        hooks_list.append(hook_def)
        target_block["hooks"] = hooks_list

        merged[event] = event_hooks

    return merged


def _teleclaude_hook_map(receiver_script: Path) -> Dict[str, Dict[str, str]]:
    """Return TeleClaude hook definitions pointing to the receiver script."""

    return {
        "SessionStart": {
            "name": "teleclaude-session-start",
            "type": "command",
            "command": f"{receiver_script} session_start",
            "description": "Notify TeleClaude of session start",
        },
        "Notification": {
            "name": "teleclaude-notification",
            "type": "command",
            "command": f"{receiver_script} notification",
            "description": "Notify TeleClaude of user input request",
        },
        "AfterModel": {
            "name": "teleclaude-stop",
            "type": "command",
            "command": f"{receiver_script} stop",
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

    # Define hooks
    # We pass event name as argument
    hooks_map = _teleclaude_hook_map(receiver_script)

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

    hooks_map = _teleclaude_hook_map(receiver_script)

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
