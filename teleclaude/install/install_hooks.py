#!/usr/bin/env python3
"""Install/Update agent hooks and settings configuration.

This script configures AI agents (Gemini, Claude, Codex) to use TeleClaude hooks
and applies required settings overrides from teleclaude/install/settings/*.json.
It idempotently merges hook definitions and settings into the agent's config files.
"""

import json
import os
import re
import shlex
import tomllib
from pathlib import Path
from typing import Any, Dict, Mapping

from teleclaude.constants import MAIN_MODULE
from teleclaude.core.events import AgentHookEvents, AgentHookEventType

SETTINGS_DIR = Path(__file__).parent / "settings"


def _load_settings_overrides(agent: str) -> dict[str, object] | None:  # guard: loose-dict - JSON from disk
    """Load static settings overrides for an agent from settings/{agent}.json."""
    path = SETTINGS_DIR / f"{agent}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


# guard: loose-dict-func - JSON settings merge operates on arbitrary nested dicts
def _deep_merge(base: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    """Recursively merge overrides into base. Override values win for leaf keys."""
    merged = base.copy()
    for key, value in overrides.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


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
KNOWN_NATIVE_HOOK_EVENTS = {
    event_name for agent_map in AgentHookEvents.HOOK_EVENT_MAP.values() for event_name in agent_map.keys()
}


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


def _build_hook_invocation(receiver_script: Path) -> str:
    """Build the base receiver invocation.

    Hooks must execute the receiver script directly; wrapper binaries or shell
    interpreters are not used to preserve direct script portability.
    """
    return shlex.quote(str(receiver_script))


def _build_hook_command(receiver_invocation: str, agent: str, event_arg: str) -> str:
    """Build command string: receiver invocation + agent context args."""
    return f'{receiver_invocation} --agent {agent} --cwd "$PWD" {event_arg}'


def _build_hook_map(
    receiver_invocation: str,
    agent: str,
    event_args: Mapping[str, AgentHookEventType],
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
            "command": _build_hook_command(receiver_invocation, agent, event_arg),
        }
        if include_metadata:
            hook_def["name"] = f"teleclaude-{event_arg}"
            hook_def["description"] = f"Notify TeleClaude of {agent.capitalize()} {event_name}"

        hooks[event_name] = hook_def

    return hooks


def _filter_receiver_handled_events(
    event_args: Mapping[str, AgentHookEventType],
) -> Dict[str, AgentHookEventType]:
    """Filter to event mappings that receiver forwards by contract."""
    return {
        event_name: event_arg
        for event_name, event_arg in event_args.items()
        if event_arg in AgentHookEvents.RECEIVER_HANDLED
    }


def _claude_hook_map(receiver_invocation: str, receiver_script: Path) -> Dict[str, Dict[str, Any]]:
    """Return TeleClaude hook definitions for Claude Code."""
    return _build_hook_map(
        receiver_invocation,
        "claude",
        _filter_receiver_handled_events(AgentHookEvents.HOOK_EVENT_MAP["claude"]),
    )


def _gemini_hook_map(receiver_invocation: str, receiver_script: Path) -> Dict[str, Dict[str, Any]]:
    """Return TeleClaude hook definitions for Gemini CLI."""
    # Installer contract:
    # - Tool lane comes only from BeforeTool/AfterTool.
    # - AfterModel is reasoning-only and must not be mapped to tool_use.
    gemini_events = dict(AgentHookEvents.HOOK_EVENT_MAP["gemini"])
    gemini_events.pop("AfterModel", None)
    gemini_events["BeforeTool"] = AgentHookEvents.TOOL_USE
    gemini_events["AfterTool"] = AgentHookEvents.TOOL_DONE
    return _build_hook_map(
        receiver_invocation,
        "gemini",
        _filter_receiver_handled_events(gemini_events),
        include_metadata=True,
    )


def _prune_agent_hooks(existing_hooks: Dict[str, Any], allowed_events: set[str]) -> Dict[str, Any]:
    """Remove TeleClaude receiver hooks from unused events.

    Keep TeleClaude hooks only for allowed_events.
    Preserve all non-TeleClaude hooks.
    """
    pruned: Dict[str, Any] = {}

    for event, blocks in existing_hooks.items():
        if not isinstance(blocks, list):
            # Drop malformed known hook-event entries (e.g. stale null values).
            # Preserve unknown non-event config keys under hooks.
            if event not in KNOWN_NATIVE_HOOK_EVENTS:
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
    hook_map_builder: Any,
    enable_hooks_flag: bool = False,
) -> None:
    """Configure hooks for JSON-based agent CLIs (Claude, Gemini).

    Args:
        repo_root: Project root
        agent: Agent name (claude, gemini)
        settings_path: Path to settings.json
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

    receiver_invocation = _build_hook_invocation(receiver_script)
    hooks_map = hook_map_builder(receiver_invocation, receiver_script)
    allowed_events = set(hooks_map.keys())

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

        hooks_cfg = settings.get("hooks")
        if not isinstance(hooks_cfg, dict):
            hooks_cfg = {}
        # Gemini expects hooks.enabled to be an array of enabled matcher names.
        # Normalize to wildcard to enable all configured hook matchers.
        hooks_cfg["enabled"] = [MATCHER_ALL]
        settings["hooks"] = hooks_cfg

    # Apply static settings overrides from settings/{agent}.json
    overrides = _load_settings_overrides(agent)
    if overrides:
        settings = _deep_merge(settings, overrides)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"{agent.capitalize()} hooks and settings configured in {settings_path}")


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    _configure_json_agent_hooks(
        repo_root,
        "claude",
        Path.home() / ".claude" / "settings.json",
        _claude_hook_map,
    )


def configure_gemini(repo_root: Path) -> None:
    """Configure Gemini CLI hooks."""
    _configure_json_agent_hooks(
        repo_root,
        "gemini",
        Path.home() / ".gemini" / "settings.json",
        _gemini_hook_map,
        enable_hooks_flag=True,
    )


def configure_codex(repo_root: Path) -> None:
    """Configure Codex CLI notify hook.

    Codex uses TOML config at ~/.codex/config.toml with a simple `notify` key
    that takes an array of command parts. Unlike Claude/Gemini which use JSON
    with nested hook structures, Codex only supports one hook event type:
    `agent-turn-complete` which maps to our internal "agent_stop" event.
    """
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver.py"
    if not receiver_script.exists():
        print(f"Warning: Codex receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)

    config_path = Path.home() / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    notify_value = [
        str(receiver_script),
        AGENT_FLAG,
        CODEX_AGENT,
    ]

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
                joined = " ".join(str(part) for part in existing_notify)
                if isinstance(existing_notify, list):
                    has_receiver = RECEIVER_FILE in joined
                    has_codex_agent = f"{AGENT_FLAG} {CODEX_AGENT}" in joined
                    is_our_hook = has_receiver and has_codex_agent

                if not is_our_hook:
                    print(f"Warning: Existing notify hook in {config_path} is not ours, skipping")
                    print(f"  Existing: {existing_notify}")
                    skip_notify_update = True
                else:
                    # Remove previous notify block and reinsert normalized block.
                    # Capture from `notify = [` up to matching closing `]`.
                    notify_block_pattern = re.compile(rf"(?ms)^\s*{re.escape(NOTIFY_KEY)}\s*=\s*\[[^\]]*?\]\s*,?\s*$")
                    content = notify_block_pattern.sub("", content).rstrip()
            if not skip_notify_update:
                # Add notify after any comments at top or before first section.
                first_section = re.search(r"^\[", content, re.MULTILINE)
                if first_section:
                    insert_pos = first_section.start()
                    if content and not content.endswith("\n"):
                        notify_line = "\n" + notify_line
                    content = content[:insert_pos] + notify_line + "\n\n" + content[insert_pos:]
                else:
                    if content and not content.endswith("\n"):
                        notify_line = "\n" + notify_line
                    content = content.rstrip() + "\n" + notify_line + "\n"
    else:
        # Create new config with just the notify hook
        notify_line = f"{NOTIFY_KEY} = {json.dumps(notify_value)}"
        content = f"# Codex CLI configuration\n\n{notify_line}\n"

    content = ensure_codex_mcp_config(content, repo_root)
    content = _apply_codex_settings_overrides(content)
    config_path.write_text(content)
    print(f"Codex hooks and settings configured in {config_path}")


def _apply_codex_settings_overrides(content: str) -> str:
    """Apply settings overrides from settings/codex.json to TOML content.

    For each top-level key in the overrides, ensure it exists in the TOML.
    Replaces existing values; appends missing keys before the first section.
    """
    overrides = _load_settings_overrides("codex")
    if not overrides:
        return content

    try:
        config = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return content

    for key, value in overrides.items():
        toml_value = json.dumps(value)
        key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)

        if key in config:
            if config[key] == value:
                continue
            content = key_pattern.sub(f"{key} = {toml_value}", content)
        else:
            # Insert before first section header
            first_section = re.search(r"^\[", content, re.MULTILINE)
            line = f"{key} = {toml_value}\n"
            if first_section:
                content = content[: first_section.start()] + line + content[first_section.start() :]
            else:
                content = content.rstrip() + "\n" + line

    return content


def ensure_codex_mcp_config(content: str, repo_root: Path) -> str:
    """Ensure Codex MCP server config points at the repo root wrapper command."""
    wrapper_path = repo_root / "bin" / "mcp-wrapper.py"

    desired_block = (
        "# TeleClaude MCP Server\n"
        "[mcp_servers.teleclaude]\n"
        'type = "stdio"\n'
        'command = "uv"\n'
        f'args = ["run", "--quiet", "--project", "{repo_root}", "{wrapper_path}"]\n'
    )

    section_name = "mcp_servers.teleclaude"
    section_pattern = re.compile(
        rf"(?ms)^(?:# TeleClaude MCP Server\n)?\[{re.escape(section_name)}\]\n"
        r"(?:^(?!\[).*$\n?)*"
    )
    content = section_pattern.sub("", content)
    content = content.rstrip() + "\n\n" + desired_block
    return content


def resolve_main_repo_root(start: Path | None = None) -> Path:
    """Resolve the main git repository root, even from a worktree.

    In a worktree, .git is a file containing 'gitdir: <path>' pointing to
    main_repo/.git/worktrees/<name>. This reads that file to find the main repo.
    Pure filesystem — no subprocess, no external deps.
    """
    if start is None:
        start = Path(__file__).resolve().parents[2]
    current = start
    while current != current.parent:
        git_path = current / ".git"
        if git_path.is_dir():
            return current
        if git_path.is_file():
            try:
                content = git_path.read_text().strip()
            except OSError:
                return current
            if content.startswith("gitdir:"):
                gitdir = Path(content.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (current / gitdir).resolve()
                for parent in gitdir.parents:
                    if parent.name == ".git":
                        return parent.parent
            return current
        current = current.parent
    return start


def main() -> None:
    repo_root = resolve_main_repo_root()
    print(f"Configuring hooks from repo: {repo_root}")

    configure_claude(repo_root)
    configure_gemini(repo_root)
    configure_codex(repo_root)


if __name__ == MAIN_MODULE:
    main()
