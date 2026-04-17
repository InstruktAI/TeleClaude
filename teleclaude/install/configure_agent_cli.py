#!/usr/bin/env python3
"""Configure TeleClaude integration for supported agent CLIs.

This module configures Claude, Gemini, and Codex to use TeleClaude wrappers,
hooks, MCP servers, and static settings overrides from
``teleclaude/install/settings/*.json``. It idempotently merges the managed
configuration into each agent CLI's user config directory.
"""

import json
import os
import re
import shlex
import shutil
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from teleclaude.constants import MAIN_MODULE
from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.project_root import resolve_main_repo_root

SETTINGS_DIR = Path(__file__).parent / "settings"


def _load_settings_overrides(agent: str) -> dict[str, object] | None:  # guard: loose-dict - JSON from disk
    """Load static settings overrides for an agent from settings/{agent}.json."""
    path = SETTINGS_DIR / f"{agent}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())  # type: ignore[no-any-return]


# guard: loose-dict-func - JSON settings merge operates on arbitrary nested dicts
def _deep_merge(base: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    """Recursively merge overrides into base. Override values win for leaf keys."""
    merged = base.copy()
    for key, value in overrides.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)  # type: ignore[arg-type]
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
CODEX_COMPACTION_PROMPT_FILENAME = "CODEX.compaction.md"
CODEX_COMPACTION_PROMPT_KEY = "experimental_compact_prompt_file"
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
        return json.loads(raw)  # type: ignore[no-any-return]
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
            # Normalize all receiver variants to a single token for dedup:
            # - legacy receiver.py / receiver_claude.py / receiver_gemini.py
            # - current receiver/__main__.py (package form)
            if (
                part.endswith(RECEIVER_FILE)
                or part.endswith(RECEIVER_CLAUDE_FILE)
                or part.endswith(RECEIVER_GEMINI_FILE)
                or part.endswith("receiver/__main__.py")
            ):
                return RECEIVER_TOKEN
            return part
    return None


def merge_hooks(existing_hooks: dict[str, Any], new_hooks: dict[str, Any]) -> dict[str, Any]:
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
) -> dict[str, dict[str, Any]]:
    """Build hook definitions for an agent.

    Args:
        python_exe: Path to Python executable
        receiver_script: Path to receiver.py script
        agent: Agent name (claude, gemini)
        event_args: Mapping of event names to event arguments
        include_metadata: If True, add name and description fields (for Gemini)
    """
    hooks: dict[str, dict[str, Any]] = {}
    for event_name, event_arg in event_args.items():
        hook_def: dict[str, Any] = {
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
) -> dict[str, AgentHookEventType]:
    """Filter to event mappings that receiver forwards by contract."""
    return {
        event_name: event_arg
        for event_name, event_arg in event_args.items()
        if event_arg in AgentHookEvents.RECEIVER_HANDLED
    }


def _claude_hook_map(receiver_invocation: str, receiver_script: Path) -> dict[str, dict[str, Any]]:  # pylint: disable=unused-argument
    """Return TeleClaude hook definitions for Claude Code."""
    return _build_hook_map(
        receiver_invocation,
        "claude",
        _filter_receiver_handled_events(AgentHookEvents.HOOK_EVENT_MAP["claude"]),
    )


def _gemini_hook_map(receiver_invocation: str, receiver_script: Path) -> dict[str, dict[str, Any]]:  # pylint: disable=unused-argument
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


def _prune_agent_hooks(  # pylint: disable=too-many-branches
    existing_hooks: dict[str, Any], allowed_events: set[str]
) -> dict[str, Any]:
    """Remove TeleClaude receiver hooks from unused events.

    Keep TeleClaude hooks only for allowed_events.
    Preserve all non-TeleClaude hooks.
    """
    pruned: dict[str, Any] = {}

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


def _configure_json_agent_hooks(  # pylint: disable=too-many-locals  # Flat data assembly is intentionally verbose.
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
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
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
    settings["hooks"] = _prune_agent_hooks(existing_hooks, allowed_events)  # type: ignore[arg-type]

    current_hooks = settings.get("hooks", {})
    settings["hooks"] = merge_hooks(current_hooks, hooks_map)  # type: ignore[arg-type]

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

    with open(settings_path, "w") as f:  # pylint: disable=unspecified-encoding
        json.dump(settings, f, indent=2)

    print(f"{agent.capitalize()} hooks and settings configured in {settings_path}")


def _load_managed_mcp_servers(repo_root: Path) -> dict[str, dict[str, object]]:
    """Load managed MCP servers from the repository source-of-truth file."""
    settings = _load_json_settings(repo_root / "mcp.json", label="Managed MCP")
    if settings is None:
        return {}

    mcp_servers = settings.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return {}

    return {name: spec for name, spec in mcp_servers.items() if isinstance(name, str) and isinstance(spec, dict)}


def _ensure_json_mcp_servers(settings_path: Path, mcp_servers_spec: dict[str, dict[str, object]], label: str) -> None:
    """Ensure managed MCP servers exist in a JSON agent settings file."""
    if not settings_path.exists():
        return

    settings = _load_json_settings(settings_path, label=label)
    if settings is None:
        return

    mcp_servers = settings.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}

    changed = False
    for name, spec in mcp_servers_spec.items():
        if mcp_servers.get(name) != spec:
            mcp_servers[name] = spec
            changed = True

    if changed:
        settings["mcpServers"] = mcp_servers
        with open(settings_path, "w") as f:  # pylint: disable=unspecified-encoding
            json.dump(settings, f, indent=2)
        print(f"{label} MCP servers updated in {settings_path}")
    else:
        print(f"{label} MCP servers already configured in {settings_path}")


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    repo_root = resolve_main_repo_root(repo_root)
    managed_mcp_servers = _load_managed_mcp_servers(repo_root)
    _configure_json_agent_hooks(
        repo_root,
        "claude",
        Path.home() / ".claude" / "settings.json",
        _claude_hook_map,
    )
    _ensure_json_mcp_servers(Path.home() / ".claude.json", managed_mcp_servers, "Claude")


def configure_gemini(repo_root: Path) -> None:
    """Configure Gemini CLI hooks."""
    repo_root = resolve_main_repo_root(repo_root)
    managed_mcp_servers = _load_managed_mcp_servers(repo_root)
    _configure_json_agent_hooks(
        repo_root,
        "gemini",
        Path.home() / ".gemini" / "settings.json",
        _gemini_hook_map,
        enable_hooks_flag=True,
    )
    _ensure_json_mcp_servers(Path.home() / ".gemini" / "settings.json", managed_mcp_servers, "Gemini")


def configure_codex(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    repo_root: Path,
) -> None:
    """Configure Codex CLI notify hook.

    Codex uses TOML config at ~/.codex/config.toml with a simple `notify` key
    that takes an array of command parts. Unlike Claude/Gemini which use JSON
    with nested hook structures, Codex only supports one hook event type:
    `agent-turn-complete` which maps to our internal "agent_stop" event.
    """
    repo_root = resolve_main_repo_root(repo_root)
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
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
                # Check if existing notify is our hook (contains receiver and --agent codex)
                is_our_hook = False
                if isinstance(existing_notify, list):
                    str_parts = [str(part) for part in existing_notify]
                    has_receiver = any(RECEIVER_TOKEN in part for part in str_parts)
                    has_agent_flag = AGENT_FLAG in str_parts
                    has_codex_name = CODEX_AGENT in str_parts
                    is_our_hook = has_receiver and has_agent_flag and has_codex_name

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

    compaction_prompt_source = SETTINGS_DIR / CODEX_COMPACTION_PROMPT_FILENAME
    compaction_prompt_target = config_path.parent / CODEX_COMPACTION_PROMPT_FILENAME
    compaction_prompt_available = compaction_prompt_source.exists()
    if compaction_prompt_available:
        shutil.copyfile(compaction_prompt_source, compaction_prompt_target)
    else:
        print(f"Warning: Codex compaction prompt not found at {compaction_prompt_source}")

    managed_mcp_servers = _load_managed_mcp_servers(repo_root)
    content = _remove_codex_mcp_config(content)
    content = _ensure_codex_mcp_servers(content, managed_mcp_servers)
    skipped_override_keys = frozenset({CODEX_COMPACTION_PROMPT_KEY}) if not compaction_prompt_available else frozenset()
    compaction_value_overrides: dict[str, object] = {}
    if compaction_prompt_available:
        # Resolve to absolute path so Codex can locate the prompt regardless of working directory.
        compaction_value_overrides[CODEX_COMPACTION_PROMPT_KEY] = str(compaction_prompt_target)
    content = _apply_codex_settings_overrides(
        content, skip_keys=skipped_override_keys, value_overrides=compaction_value_overrides or None
    )
    config_path.write_text(content)
    print(f"Codex hooks and settings configured in {config_path}")


def _remove_codex_top_level_key(content: str, key: str) -> str:
    """Remove a top-level scalar key assignment from Codex TOML content."""
    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*(?:\n|$)", re.MULTILINE)
    return key_pattern.sub("", content)


def _apply_codex_settings_overrides(
    content: str,
    *,
    skip_keys: frozenset[str] = frozenset(),
    value_overrides: dict[str, object] | None = None,
) -> str:
    """Apply settings overrides from settings/codex.json to TOML content.

    For each top-level key in the overrides, ensure it exists in the TOML.
    Replaces existing values; appends missing keys before the first section.
    Callers may supply ``value_overrides`` to substitute specific key values
    (e.g. to write an absolute path where codex.json stores a relative placeholder).
    """
    overrides = _load_settings_overrides("codex")
    if not overrides:
        return content

    try:
        config = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return content

    for key in skip_keys:
        content = _remove_codex_top_level_key(content, key)
        config.pop(key, None)

    for key, value in overrides.items():
        if key in skip_keys:
            continue
        resolved_value = (value_overrides or {}).get(key, value)
        toml_value = json.dumps(resolved_value)
        key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)

        if key in config:
            if config[key] == resolved_value:
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


def _remove_codex_mcp_config(content: str) -> str:
    """Remove TeleClaude MCP server section from Codex TOML config."""
    section_name = "mcp_servers.teleclaude"
    section_pattern = re.compile(
        rf"(?m)^(?:[ \t]*#\s*TeleClaude MCP Server[ \t]*\n)?[ \t]*\[{re.escape(section_name)}\]\n"
        r"(?:^(?![ \t]*\[).*(?:\n|$))*"
    )
    content = section_pattern.sub("", content)
    return content.rstrip() + "\n" if content.strip() else ""


def _ensure_codex_mcp_servers(content: str, mcp_servers_spec: dict[str, dict[str, object]]) -> str:
    """Ensure managed MCP server sections exist in Codex TOML config."""
    try:
        config = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return content

    existing_mcp = config.get("mcp_servers", {})

    for name, base_spec in mcp_servers_spec.items():
        spec = dict(base_spec)
        spec["type"] = "stdio"
        if name in existing_mcp and existing_mcp[name] == spec:
            continue

        # Remove existing section if present (will be re-added)
        section_pattern = re.compile(
            rf"(?m)^[ \t]*\[mcp_servers\.{re.escape(name)}\]\n"
            r"(?:^(?![ \t]*\[).*(?:\n|$))*"
        )
        content = section_pattern.sub("", content)

        # Build TOML section
        lines = [f"\n  [mcp_servers.{name}]"]
        for key, value in spec.items():
            lines.append(f"    {key}={json.dumps(value)}")
        block = "\n".join(lines) + "\n"

        # Insert after [mcp_servers] header or append
        mcp_header = re.search(r"^\[mcp_servers\]\s*$", content, re.MULTILINE)
        if mcp_header:
            # Find end of mcp_servers section (next top-level section or EOF)
            next_section = re.search(r"^\[[^\.]", content[mcp_header.end() :], re.MULTILINE)
            if next_section:
                insert_pos = mcp_header.end() + next_section.start()
            else:
                insert_pos = len(content.rstrip())
            content = content[:insert_pos] + block + content[insert_pos:]
        else:
            content = content.rstrip() + "\n\n[mcp_servers]" + block

    return content


def install_env_symlink(repo_root: Path) -> None:
    """Symlink ~/.teleclaude/.env to the project .env for MCP server env loading."""
    project_env = repo_root / ".env"
    from teleclaude.paths import ENV_PATH  # pylint: disable=import-outside-toplevel

    target = ENV_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    if not project_env.exists():
        print(f"Warning: No .env found at {project_env}, skipping symlink")
        return

    if target.is_symlink():
        if target.resolve() == project_env.resolve():
            print(f".env symlink already configured at {target}")
            return
        target.unlink()
    elif target.exists():
        print(f"Warning: {target} exists and is not a symlink, skipping")
        return

    target.symlink_to(project_env)
    print(f".env symlink installed: {target} -> {project_env}")


def main() -> None:
    """CLI entrypoint for configuring supported agent CLIs."""
    repo_root = resolve_main_repo_root(Path(__file__).resolve().parents[2])
    print(f"Configuring agent CLIs from repo: {repo_root}")

    install_env_symlink(repo_root)
    configure_claude(repo_root)
    configure_gemini(repo_root)
    configure_codex(repo_root)


if __name__ == MAIN_MODULE:
    main()
