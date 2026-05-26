#!/usr/bin/env python3
"""Configure TeleClaude integration for supported agent CLIs.

This module configures Claude, Gemini, and Codex to use TeleClaude wrappers,
hooks, MCP servers, and static settings overrides from
``teleclaude/install/settings/``. It idempotently merges the managed
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
from teleclaude.install.codex_hooks_install import (
    all_positions_per_label,
    first_positions_per_label,
    foreign_remap_per_label,
    merge_codex_hook_trust_state,
    write_codex_hooks_json,
)
from teleclaude.paths import BIN_DIR, ENV_PATH, SHELL_DIR
from teleclaude.project_root import resolve_state_root

SETTINGS_DIR = Path(__file__).parent / "settings"
WRAPPER_TEMPLATE_DIR = Path(__file__).parent / "wrappers"
SHELL_TEMPLATE_DIR = Path(__file__).parent / "shell"

# Source filename (in repo) → installed filename (under SHELL_DIR). The
# installed names carry the leading dot that shells expect; the repo
# names omit it so the files surface naturally in directory listings
# and don't pretend to be hidden config in our tree.
_SHELL_RC_PAIRS: tuple[tuple[str, str], ...] = (
    ("zshenv", ".zshenv"),
    ("zshrc", ".zshrc"),
    ("bashenv", ".bashenv"),
    ("bashrc", ".bashrc"),
    ("profile", ".profile"),
)


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


_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(key: str) -> str:
    """Quote a TOML key if it contains special characters."""
    if _BARE_KEY_RE.match(key):
        return key
    return json.dumps(key)


def _toml_scalar(value: object) -> str:
    """Serialize a Python scalar to a TOML value literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return json.dumps(value)
    msg = f"Cannot serialize {type(value).__name__} to TOML"
    raise TypeError(msg)


def _serialize_toml(config: dict[str, object]) -> str:
    """Serialize a config dict to TOML text, recursing into nested tables."""
    lines: list[str] = []
    _emit_toml_table(lines, config, prefix=())
    return "\n".join(lines) + "\n"


def _emit_toml_table(
    lines: list[str],
    table: dict[str, object],
    *,
    prefix: tuple[str, ...],
) -> None:
    """Emit one TOML table at ``prefix`` and recurse into its sub-tables."""
    scalars = [(key, value) for key, value in table.items() if not isinstance(value, dict)]
    subtables = [(key, value) for key, value in table.items() if isinstance(value, dict)]

    if prefix and scalars:
        if lines and lines[-1] != "":
            lines.append("")
        header = ".".join(_toml_key(part) for part in prefix)
        lines.append(f"[{header}]")
        indent = "  "
    else:
        indent = ""

    for key, value in scalars:
        lines.append(f"{indent}{_toml_key(key)} = {_toml_scalar(value)}")

    for key, sub_dict in subtables:
        _emit_toml_table(lines, sub_dict, prefix=(*prefix, key))


PY_EXTENSION = ".py"
RECEIVER_TOKEN = "receiver"
RECEIVER_FILE = "receiver.py"
RECEIVER_CLAUDE_FILE = "receiver_claude.py"
RECEIVER_AGY_FILE = "receiver_agy.py"
MATCHER_KEY = "matcher"
MATCHER_ALL = "*"
NOTIFY_KEY = "notify"
AGENT_FLAG = "--agent"
CODEX_AGENT = "codex"
CODEX_COMPACTION_PROMPT_FILENAME = "CODEX.compaction.md"
CODEX_COMPACTION_PROMPT_KEY = "experimental_compact_prompt_file"
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


def _load_user_json_or_refuse(
    path: Path, *, label: str
) -> dict[str, object]:  # guard: loose-dict - settings are dynamic JSON
    """Load an existing user-owned JSON file, refusing to clobber it when malformed.

    A missing file yields an empty mapping (safe to create); an existing file
    that fails to parse stops the run so the user's content is never overwritten.
    """
    data = _load_json_settings(path, label=label)
    if data is None:
        raise RuntimeError(f"Refusing to overwrite invalid {label} file at {path}; fix or remove it, then re-run.")
    return data


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
            # - legacy receiver.py / receiver_claude.py / receiver_agy.py
            # - current receiver/__main__.py (package form)
            if (
                part.endswith(RECEIVER_FILE)
                or part.endswith(RECEIVER_CLAUDE_FILE)
                or part.endswith(RECEIVER_AGY_FILE)
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


def _build_hook_command_without_event(receiver_invocation: str, agent: str) -> str:
    """Build command string without a positional event argument."""
    return f'{receiver_invocation} --agent {agent} --cwd "$PWD"'


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
    event_args: Mapping[str, AgentHookEventType | None],
) -> dict[str, AgentHookEventType]:
    """Filter to event mappings that receiver forwards by contract."""
    return {
        event_name: event_arg
        for event_name, event_arg in event_args.items()
        if event_arg is not None and event_arg in AgentHookEvents.RECEIVER_HANDLED
    }


def _claude_hook_map(receiver_invocation: str, receiver_script: Path) -> dict[str, dict[str, Any]]:
    """Return TeleClaude hook definitions for Claude Code."""
    return _build_hook_map(
        receiver_invocation,
        "claude",
        _filter_receiver_handled_events(AgentHookEvents.HOOK_EVENT_MAP["claude"]),
    )


def _codex_hook_blocks(receiver_invocation: str, receiver_script: Path) -> dict[str, list[dict[str, Any]]]:
    """Return TeleClaude native hook blocks for Codex."""
    command = _build_hook_command_without_event(receiver_invocation, CODEX_AGENT)
    return {
        "SessionStart": [
            {
                "matcher": "startup|resume",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "statusMessage": "Loading session notes",
                    }
                ],
            }
        ],
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                    }
                ]
            }
        ],
        "PreToolUse": [
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": 30,
                    }
                ]
            }
        ],
    }


def _prune_agent_hooks(existing_hooks: dict[str, Any], allowed_events: set[str]) -> dict[str, Any]:
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

    with open(settings_path, "w") as f:
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
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"{label} MCP servers updated in {settings_path}")
    else:
        print(f"{label} MCP servers already configured in {settings_path}")


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    repo_root = resolve_state_root(repo_root)
    managed_mcp_servers = _load_managed_mcp_servers(repo_root)
    _configure_json_agent_hooks(
        repo_root,
        "claude",
        Path.home() / ".claude" / "settings.json",
        _claude_hook_map,
    )
    _ensure_json_mcp_servers(Path.home() / ".claude.json", managed_mcp_servers, "Claude")


def configure_agy(repo_root: Path) -> None:
    """Configure Antigravity CLI (agy) hooks, settings, and MCP."""
    repo_root = resolve_state_root(repo_root)
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    if not receiver_script.exists():
        print(f"Warning: Antigravity receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)

    agy_dir = Path.home() / ".gemini" / "antigravity-cli"
    agy_dir.mkdir(parents=True, exist_ok=True)

    # 1. Merge static settings overrides into ~/.gemini/antigravity-cli/settings.json
    settings_path = agy_dir / "settings.json"
    settings = _load_user_json_or_refuse(settings_path, label="Antigravity")
    overrides = _load_settings_overrides("gemini")
    if overrides:
        settings = _deep_merge(settings, overrides)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"Antigravity settings configured in {settings_path}")

    # 2. Translates MCP settings and writes to ~/.gemini/antigravity-cli/mcp_config.json
    mcp_config_path = agy_dir / "mcp_config.json"
    mcp_config = _load_user_json_or_refuse(mcp_config_path, label="Antigravity MCP")
    managed_mcp_servers = _load_managed_mcp_servers(repo_root)
    existing_mcp_servers = mcp_config.get("mcpServers", {})
    if not isinstance(existing_mcp_servers, dict):
        existing_mcp_servers = {}

    changed = False
    for name, spec in managed_mcp_servers.items():
        if existing_mcp_servers.get(name) != spec:
            existing_mcp_servers[name] = spec
            changed = True

    if changed or not mcp_config:
        mcp_config["mcpServers"] = existing_mcp_servers
        with open(mcp_config_path, "w") as f:
            json.dump(mcp_config, f, indent=2)
        print(f"Antigravity MCP configured in {mcp_config_path}")

    # 3. Automatically writes Modular Hooks config file to ~/.gemini/config/hooks.json under "teleclaude" group
    hooks_dir = Path.home() / ".gemini" / "config"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path = hooks_dir / "hooks.json"

    hooks_data = _load_user_json_or_refuse(hooks_path, label="Antigravity Hooks")

    receiver_invocation = _build_hook_invocation(receiver_script)

    # agy exposes no SessionStart hook — its lifecycle is PreInvocation /
    # PostInvocation / PreToolUse / PostToolUse / Stop. TeleClaude synthesizes
    # session_start from the first activity event (see AgyAdapter), so only the
    # events agy actually fires are installed here.
    agy_events_mapping = {
        "PreInvocation": "user_prompt_submit",
        "PreToolUse": "tool_use",
        "Stop": "agent_stop",
    }

    teleclaude_hooks = {
        event_name: [{"type": "command", "command": _build_hook_command(receiver_invocation, "gemini", event_arg)}]
        for event_name, event_arg in agy_events_mapping.items()
    }

    hooks_data["teleclaude"] = teleclaude_hooks

    with open(hooks_path, "w") as f:
        json.dump(hooks_data, f, indent=2)
    print(f"Antigravity hooks configured in {hooks_path}")


def configure_codex(
    repo_root: Path,
) -> None:
    """Configure native Codex hooks and settings."""
    repo_root = resolve_state_root(repo_root)
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    if not receiver_script.exists():
        print(f"Warning: Codex receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)

    config_path = Path.home() / ".codex" / "config.toml"
    hooks_path = config_path.parent / "hooks.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        try:
            config: dict[str, object] = tomllib.loads(config_path.read_text())
        except tomllib.TOMLDecodeError as exc:
            print(f"Warning: Failed to parse Codex config: {exc}")
            return
    else:
        config = {}

    config.pop(NOTIFY_KEY, None)

    overrides_path = SETTINGS_DIR / "codex.toml"
    if overrides_path.exists():
        try:
            overrides: dict[str, object] = tomllib.loads(overrides_path.read_text())
        except tomllib.TOMLDecodeError as exc:
            print(f"Warning: Failed to parse Codex overrides: {exc}")
            overrides = {}
        config = _deep_merge(config, overrides)

    compaction_prompt_source = SETTINGS_DIR / CODEX_COMPACTION_PROMPT_FILENAME
    compaction_prompt_target = config_path.parent / CODEX_COMPACTION_PROMPT_FILENAME
    if compaction_prompt_source.exists():
        shutil.copyfile(compaction_prompt_source, compaction_prompt_target)
        config[CODEX_COMPACTION_PROMPT_KEY] = str(compaction_prompt_target)
    else:
        print(f"Warning: Codex compaction prompt not found at {compaction_prompt_source}")
        config.pop(CODEX_COMPACTION_PROMPT_KEY, None)

    managed_mcp_servers = _load_managed_mcp_servers(repo_root)
    if managed_mcp_servers:
        mcp = config.get("mcp_servers", {})
        if not isinstance(mcp, dict):
            mcp = {}
        mcp.pop("teleclaude", None)
        for name, base_spec in managed_mcp_servers.items():
            spec = dict(base_spec)
            spec["type"] = "stdio"
            mcp[name] = spec
        config["mcp_servers"] = mcp

    receiver_invocation = _build_hook_invocation(receiver_script)
    managed_hook_blocks = _codex_hook_blocks(receiver_invocation, receiver_script)
    write_result = write_codex_hooks_json(
        hooks_path,
        managed_hook_blocks,
        load_settings=_load_json_settings,
        prune=_prune_agent_hooks,
        extract_receiver_script=_extract_receiver_script,
    )

    receiver_command = _build_hook_command_without_event(receiver_invocation, CODEX_AGENT)
    merge_codex_hook_trust_state(
        config,
        hooks_path=hooks_path,
        receiver_command=receiver_command,
        new_positions=first_positions_per_label(write_result.new_positions),
        old_positions_by_label=all_positions_per_label(write_result.old_positions),
        foreign_remap_by_label=foreign_remap_per_label(write_result.foreign_remap),
    )

    config_path.write_text(_serialize_toml(config))
    print(f"Codex hooks and settings configured in {config_path}")


def install_agent_wrapper(repo_root: Path, wrapper_name: str) -> None:
    """Install an agent-session wrapper as a symlink into ~/.teleclaude/bin.

    Creates a symlink from ~/.teleclaude/bin/{name} -> {repo_root}/teleclaude/install/wrappers/{name}.
    Migrates from old rendered-copy installs by replacing regular files with symlinks.
    """
    _ = repo_root  # kept for call-site compatibility; source path uses WRAPPER_TEMPLATE_DIR
    source_path = WRAPPER_TEMPLATE_DIR / wrapper_name
    if not source_path.exists():
        print(f"Warning: wrapper source missing: {source_path}")
        return

    bin_dir = BIN_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    target_path = bin_dir / wrapper_name

    # Already a correct symlink — nothing to do
    if target_path.is_symlink() and target_path.resolve() == source_path.resolve():
        print(f"{wrapper_name} wrapper already linked at {target_path}")
        return

    # Remove stale file or incorrect symlink before creating new symlink
    if target_path.exists() or target_path.is_symlink():
        target_path.unlink()

    target_path.symlink_to(source_path)
    print(f"{wrapper_name} wrapper linked at {target_path} -> {source_path}")


def install_shell_environment() -> None:
    """Symlink ~/.teleclaude/shell/.{zshenv,zshrc,bashenv,bashrc,profile}
    onto the repo-tracked source files in teleclaude/install/shell/.

    Mirrors ``install_agent_wrapper``: idempotent (skips if symlink is
    already correct), replaces stale files or wrong symlinks. The
    installed tree is the source of truth read by tmux-session shells
    once ZDOTDIR/BASH_ENV/ENV point at it.
    """
    SHELL_DIR.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in _SHELL_RC_PAIRS:
        source_path = SHELL_TEMPLATE_DIR / source_name
        if not source_path.exists():
            print(f"Warning: shell rc source missing: {source_path}")
            continue
        target_path = SHELL_DIR / target_name

        if target_path.is_symlink() and target_path.resolve() == source_path.resolve():
            print(f"shell rc already linked: {target_path}")
            continue

        if target_path.exists() or target_path.is_symlink():
            target_path.unlink()

        target_path.symlink_to(source_path)
        print(f"shell rc linked: {target_path} -> {source_path}")


def install_env_symlink(repo_root: Path) -> None:
    """Symlink ~/.teleclaude/.env to the project .env for MCP server env loading."""
    project_env = repo_root / ".env"
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
    repo_root = resolve_state_root(Path(__file__).resolve().parents[2])
    print(f"Configuring agent CLIs from repo: {repo_root}")

    install_agent_wrapper(repo_root, "git")
    install_agent_wrapper(repo_root, "teleclaude-shell")
    install_shell_environment()
    install_env_symlink(repo_root)
    configure_claude(repo_root)
    configure_agy(repo_root)
    configure_codex(repo_root)


if __name__ == MAIN_MODULE:
    main()
