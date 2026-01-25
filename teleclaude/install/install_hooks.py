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

from teleclaude.constants import MAIN_MODULE

PY_EXTENSION = ".py"
RECEIVER_TOKEN = "receiver"
RECEIVER_FILE = "receiver.py"
RECEIVER_CLAUDE_FILE = "receiver_claude.py"
RECEIVER_GEMINI_FILE = "receiver_gemini.py"
MATCHER_KEY = "matcher"
MATCHER_ALL = "*"
NOTIFY_KEY = "notify"
AGENT_FLAG = "--agent"
CODEX_AGENT = "codex"
CODEX_NOTIFY_SUFFIX = [AGENT_FLAG, CODEX_AGENT]


def _load_json_settings(
    path: Path, *, label: str
) -> dict[str, object] | None:  # guard: loose-dict - settings are dynamic JSON
    if not path.exists():
        return {}

    raw = path.read_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Warning: Failed to load {label} settings (invalid JSON): {exc}")
        return None


def _extract_receiver_script(command: str | list[object]) -> str | None:
    if isinstance(command, list):
        parts = [str(part) for part in command]
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            return None
    for part in parts:
        if part.endswith(PY_EXTENSION) and RECEIVER_TOKEN in part:
            # Normalize legacy receiver_claude/receiver_gemini to receiver.py family
            if (
                part.endswith(RECEIVER_FILE)
                or part.endswith(RECEIVER_CLAUDE_FILE)
                or part.endswith(RECEIVER_GEMINI_FILE)
            ):
                return RECEIVER_TOKEN
            return part
    return None


def merge_hooks(existing_hooks: Dict[str, Any], new_hooks: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently merge new hooks into existing hooks configuration.

    Deduplicates by receiver script path so old hook entries are replaced.
    """
    merged = existing_hooks.copy()

    for event, hook_def in new_hooks.items():
        event_hooks = merged.get(event, [])
        if not isinstance(event_hooks, list):
            event_hooks = []
        event_hooks = [b for b in event_hooks if isinstance(b, dict)]

        # Structure: [{"matcher": "*", "hooks": [...]}]
        # We target the "*" matcher block or create one

        target_block = None
        for block in event_hooks:
            if block.get(MATCHER_KEY) == MATCHER_ALL:
                target_block = block
                break

        if not target_block:
            target_block = {MATCHER_KEY: MATCHER_ALL, "hooks": []}
            event_hooks.append(target_block)

        # Update specific hook within the block
        hooks_list = target_block.get("hooks", [])
        if not isinstance(hooks_list, list):
            hooks_list = []
        hooks_list = [h for h in hooks_list if isinstance(h, dict)]

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


def _build_hook_command(python_exe: Path, receiver_script: Path, agent: str, event_arg: str) -> str:
    """Build command string: python executable + script + args, space-separated."""
    return f"{python_exe} {receiver_script} --agent {agent} {event_arg}"


# Event mappings by agent
CLAUDE_EVENTS = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "prompt",
    "Stop": "stop",
}

GEMINI_EVENTS = {
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    # AfterAgent fires when agent loop ends = turn completion = stop event
    "AfterAgent": "stop",
    "Notification": "notification",
    "BeforeAgent": "before_agent",
    "BeforeModel": "before_model",
    "AfterModel": "after_model",
    "BeforeToolSelection": "before_tool_selection",
    "BeforeTool": "before_tool",
    "AfterTool": "after_tool",
    "PreCompress": "pre_compress",
}


def _build_hook_map(
    python_exe: Path,
    receiver_script: Path,
    agent: str,
    event_args: Dict[str, str],
    include_metadata: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Build hook definitions for an agent.

    Args:
        python_exe: Path to Python executable
        receiver_script: Path to receiver.py script
        agent: Agent name (claude, gemini)
        event_args: Mapping of event names to event arguments
        include_metadata: If True, add name and description fields (for Gemini)
    """
    hooks: Dict[str, Dict[str, Any]] = {}
    for event_name, event_arg in event_args.items():
        hook_def: Dict[str, Any] = {
            "type": "command",
            "command": _build_hook_command(python_exe, receiver_script, agent, event_arg),
        }
        if include_metadata:
            hook_def["name"] = f"teleclaude-{event_arg}"
            hook_def["description"] = f"Notify TeleClaude of {agent.capitalize()} {event_name}"

        hooks[event_name] = hook_def

    return hooks


def _claude_hook_map(python_exe: Path, receiver_script: Path) -> Dict[str, Dict[str, Any]]:
    """Return TeleClaude hook definitions for Claude Code."""
    return _build_hook_map(python_exe, receiver_script, "claude", CLAUDE_EVENTS)


def _gemini_hook_map(python_exe: Path, receiver_script: Path) -> Dict[str, Dict[str, Any]]:
    """Return TeleClaude hook definitions for Gemini CLI."""
    return _build_hook_map(python_exe, receiver_script, "gemini", GEMINI_EVENTS, include_metadata=True)


def _prune_agent_hooks(existing_hooks: Dict[str, Any], allowed_events: set[str]) -> Dict[str, Any]:
    """Remove TeleClaude receiver hooks from unused events.

    Keep TeleClaude hooks only for allowed_events.
    Preserve all non-TeleClaude hooks.
    """
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
                    if _extract_receiver_script(cmd) == RECEIVER_TOKEN:
                        continue
                    filtered_hooks.append(hook)

            if filtered_hooks:
                updated_block = block.copy()
                updated_block["hooks"] = filtered_hooks
                new_blocks.append(updated_block)

        if new_blocks:
            pruned[event] = new_blocks

    return pruned


def _configure_json_agent_hooks(
    repo_root: Path,
    agent: str,
    settings_path: Path,
    allowed_events: set[str],
    hook_map_builder: Any,
    enable_hooks_flag: bool = False,
) -> None:
    """Configure hooks for JSON-based agent CLIs (Claude, Gemini).

    Args:
        repo_root: Project root
        agent: Agent name (claude, gemini)
        settings_path: Path to settings.json
        allowed_events: Events to keep TeleClaude hooks for
        hook_map_builder: Function that returns hook map
        enable_hooks_flag: If True, set tools.enableHooks = True (for Gemini)
    """
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver.py"
    if not receiver_script.exists():
        print(f"Warning: {agent.capitalize()} receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _load_json_settings(settings_path, label=agent.capitalize())
    if settings is None:
        return

    python_exe = _resolve_hook_python(repo_root)
    hooks_map = hook_map_builder(python_exe, receiver_script)

    existing_hooks = settings.get("hooks", {})
    settings["hooks"] = _prune_agent_hooks(existing_hooks, allowed_events)

    current_hooks = settings.get("hooks", {})
    settings["hooks"] = merge_hooks(current_hooks, hooks_map)

    if enable_hooks_flag:
        tools_cfg = settings.get("tools")
        if not isinstance(tools_cfg, dict):
            tools_cfg = {}
        tools_cfg["enableHooks"] = True
        settings["tools"] = tools_cfg

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"{agent.capitalize()} hooks configured in {settings_path}")


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    _configure_json_agent_hooks(
        repo_root,
        "claude",
        Path.home() / ".claude" / "settings.json",
        set(CLAUDE_EVENTS.keys()),
        _claude_hook_map,
    )


def configure_gemini(repo_root: Path) -> None:
    """Configure Gemini CLI hooks."""
    _configure_json_agent_hooks(
        repo_root,
        "gemini",
        Path.home() / ".gemini" / "settings.json",
        set(GEMINI_EVENTS.keys()),
        _gemini_hook_map,
        enable_hooks_flag=True,
    )


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
    notify_value = [str(python_exe), str(receiver_script), AGENT_FLAG, CODEX_AGENT]

    if config_path.exists():
        content = config_path.read_text()
        try:
            config = tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            print(f"Warning: Failed to parse Codex config: {e}")
            return

        existing_notify = config.get(NOTIFY_KEY)
        skip_notify_update = False
        if existing_notify == notify_value:
            print(f"Codex notify hook already configured in {config_path}")
            skip_notify_update = True

        if not skip_notify_update:
            # Update or add notify line using text manipulation to preserve formatting
            notify_line = f"{NOTIFY_KEY} = {json.dumps(notify_value)}"
            if NOTIFY_KEY in config:
                # Check if existing notify is our hook (contains receiver.py and --agent codex)
                is_our_hook = False
                if isinstance(existing_notify, list):
                    joined = " ".join(str(part) for part in existing_notify)
                    has_receiver = RECEIVER_FILE in joined
                    has_codex_agent = AGENT_FLAG in existing_notify and CODEX_AGENT in existing_notify
                    is_our_hook = has_receiver and has_codex_agent
                if not is_our_hook:
                    print(f"Warning: Existing notify hook in {config_path} is not ours, skipping")
                    print(f"  Existing: {existing_notify}")
                    skip_notify_update = True
                else:
                    # Replace our existing notify line with updated paths
                    cleaned_lines: list[str] = []
                    for line in content.splitlines():
                        if re.match(rf"^\s*{NOTIFY_KEY}\s*=", line):
                            continue
                        cleaned_lines.append(line)
                    content = "\n".join(cleaned_lines).rstrip()
                    first_section = re.search(r"^\[", content, re.MULTILINE)
                    if first_section:
                        insert_pos = first_section.start()
                        content = content[:insert_pos] + notify_line + "\n\n" + content[insert_pos:]
                    else:
                        content = content + "\n" + notify_line + "\n"
            if not skip_notify_update and NOTIFY_KEY not in config:
                # Add notify after any comments at the top, before first section
                first_section = re.search(r"^\[", content, re.MULTILINE)
                if first_section:
                    insert_pos = first_section.start()
                    content = content[:insert_pos] + notify_line + "\n\n" + content[insert_pos:]
                else:
                    content = content.rstrip() + "\n\n" + notify_line + "\n"
    else:
        # Create new config with just the notify hook
        notify_line = f"{NOTIFY_KEY} = {json.dumps(notify_value)}"
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
        'type = "stdio"\n'
        f'command = "{venv_python}"\n'
        f'args = ["{wrapper_path}"]\n'
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
    # Repo root is parent of the teleclaude package directory.
    repo_root = Path(__file__).resolve().parents[2]
    print(f"Configuring hooks from repo: {repo_root}")

    configure_claude(repo_root)
    configure_gemini(repo_root)
    configure_codex(repo_root)


if __name__ == MAIN_MODULE:
    main()
