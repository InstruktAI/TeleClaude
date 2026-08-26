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

from dotenv import dotenv_values

from teleclaude.constants import MAIN_MODULE
from teleclaude.hooks.adapters import get_adapter
from teleclaude.install.codex_hooks_install import (
    all_positions_per_label,
    first_positions_per_label,
    foreign_remap_per_label,
    merge_codex_hook_trust_state,
    write_codex_hooks_json,
)
from teleclaude.install.dsh_hooks_install import configure_dsh
from teleclaude.install.mcp_config import load_managed_mcp_server_names as _load_managed_mcp_server_names
from teleclaude.mcp.registry import load_effective_registry as _load_effective_registry
from teleclaude.paths import BIN_DIR, ENV_PATH, SHELL_DIR, ConfigFileName
from teleclaude.project_root import resolve_project_root

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
HOOKS_KEY = "hooks"
HOOK_TYPE_KEY = "type"
HOOK_COMMAND_KEY = "command"
HOOK_COMMAND_TYPE = "command"
NOTIFY_KEY = "notify"
AGENT_FLAG = "--agent"
CODEX_AGENT = "codex"
AGY_AGENT = "gemini"
CLAUDE_AGENT = "claude"
DEEPSEEK_AGENT = "deepseek"
CODEX_COMPACTION_PROMPT_FILENAME = "CODEX.compaction.md"
CODEX_COMPACTION_PROMPT_KEY = "experimental_compact_prompt_file"


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


def _load_user_json_or_blank_or_refuse(
    path: Path, *, label: str
) -> dict[str, object]:  # guard: loose-dict - settings are dynamic JSON
    """Load a user JSON file, treating a zero-byte placeholder as empty."""
    if path.exists() and not path.read_text().strip():
        return {}
    return _load_user_json_or_refuse(path, label=label)


def _optional_object(settings: dict[str, object], key: str, *, label: str) -> dict[str, object]:
    """Return an optional object-valued settings member, failing on malformed values."""
    if key not in settings:
        return {}
    value = settings[key]
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid {label}: {key} must be an object.")
    return dict(value)


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


def _compose_static_hook_blocks(hooks: dict[str, Any], static_hooks: dict[str, Any]) -> dict[str, Any]:
    """Fold TeleClaude's own static hook blocks into the generated owned set.

    Blocks are matched by matcher: a static block replaces the same-matcher block
    already deployed, so repeated configuration runs stay idempotent and an edited
    static block supersedes its deployed copy. Generated receiver blocks carry a
    different matcher and are preserved.
    """
    composed = dict(hooks)
    for event, blocks in static_hooks.items():
        if not isinstance(blocks, list):
            continue
        static_blocks = [block for block in blocks if isinstance(block, dict)]
        static_matchers = {block.get(MATCHER_KEY) for block in static_blocks}
        deployed = composed.get(event, [])
        if not isinstance(deployed, list):
            deployed = []
        kept = [
            block for block in deployed if isinstance(block, dict) and block.get(MATCHER_KEY) not in static_matchers
        ]
        composed[event] = kept + static_blocks
    return composed


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
    event_args: Mapping[str, str],
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


def _registered_hook_events(agent: str) -> frozenset[str]:
    """Return every native event declared by the provider adapter manifest."""
    adapter = get_adapter(agent)
    return adapter.registered_events


def _declared_hook_map(agent: str) -> dict[str, str]:
    """Map every registered native event to its own receiver event argument."""
    return {event_name: event_name for event_name in _registered_hook_events(agent)}


def _claude_hook_map(receiver_invocation: str, receiver_script: Path) -> dict[str, dict[str, Any]]:
    """Return TeleClaude hook definitions for Claude Code."""
    return _build_hook_map(
        receiver_invocation,
        "claude",
        _declared_hook_map("claude"),
    )


def _codex_hook_blocks(receiver_invocation: str, receiver_script: Path) -> dict[str, list[dict[str, Any]]]:
    """Return TeleClaude native hook blocks for Codex."""
    command = _build_hook_command_without_event(receiver_invocation, CODEX_AGENT)
    blocks: dict[str, list[dict[str, Any]]] = {}
    for event_name in _registered_hook_events(CODEX_AGENT):
        if event_name == "SessionStart":
            blocks[event_name] = [
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
            ]
        elif event_name in {"PreToolUse", "PostToolUse"}:
            blocks[event_name] = [
                {
                    "matcher": ".*",
                    "hooks": [{"type": "command", "command": command}],
                }
            ]
        elif event_name == "Stop":
            blocks[event_name] = [{"hooks": [{"type": "command", "command": command, "timeout": 30}]}]
        else:
            blocks[event_name] = [
                {
                    "hooks": [{"type": "command", "command": command}],
                }
            ]
    return blocks


def _configure_dsh(repo_root: Path) -> None:
    """Build and persist TeleClaude's global DSH receiver hooks."""
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    if not receiver_script.exists():
        print(f"Warning: DeepSeek receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)
    receiver_invocation = _build_hook_invocation(receiver_script)
    hooks_map: dict[str, Any] = _build_hook_map(
        receiver_invocation,
        "deepseek",
        _declared_hook_map("deepseek"),
    )
    # The receiver legitimately writes outside the agent workspace (state dir,
    # outbox DB), so its hooks declare the explicit unsandboxed opt-in the
    # dsh-hooks plugin requires for full-access hook execution.
    for hook_def in hooks_map.values():
        if isinstance(hook_def, dict):
            hook_def["unsandboxed"] = True
    configure_dsh(
        hooks_map=hooks_map,
        merge_hook_maps=merge_hooks,
        prune_hook_maps=_prune_agent_hooks,
    )


def _prune_agent_hooks(existing_hooks: dict[str, Any], allowed_events: set[str]) -> dict[str, Any]:
    """Remove TeleClaude receiver hooks from unused events.

    Keep TeleClaude hooks only for allowed_events.
    Preserve all non-TeleClaude hooks.
    """
    pruned: dict[str, Any] = {}

    for event, blocks in existing_hooks.items():
        if not isinstance(blocks, list):
            # Ownership cannot be established without a list of hook commands.
            # Preserve opaque provider/user configuration; merge_hooks replaces
            # malformed values for events TeleClaude actively installs.
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

    # Apply static settings overrides from settings/{agent}.json. Hook blocks are
    # TeleClaude-owned and compose with the generated set; routing them through the
    # generic merge would replace an event's generated blocks wholesale.
    overrides = _load_settings_overrides(agent)
    if overrides:
        static_hooks = overrides.get(HOOKS_KEY)
        if isinstance(static_hooks, dict):
            settings[HOOKS_KEY] = _compose_static_hook_blocks(
                settings.get(HOOKS_KEY, {}),  # type: ignore[arg-type]
                static_hooks,
            )
        settings = _deep_merge(settings, {key: value for key, value in overrides.items() if key != HOOKS_KEY})

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"{agent.capitalize()} hooks and settings configured in {settings_path}")


def _purge_legacy_mcp_env(settings_path: Path, repo_root: Path) -> None:
    """Remove MCP credential values a prior setup published into agent settings.

    Ownership is proven per entry: the name is referenced by a managed MCP
    server and the stored value equals the TeleClaude environment value.
    Entries failing either condition are user-owned and preserved.
    """
    referenced = {
        name for server in _load_effective_registry(repo_root).servers.values() for name in server.env_references
    }
    if not referenced:
        return
    settings = _load_json_settings(settings_path, label="Claude")
    if not settings:
        return
    env_block = settings.get("env")
    if not isinstance(env_block, dict):
        return
    env_values = dotenv_values(ENV_PATH)
    removed = sorted(name for name in referenced if name in env_block and env_block.get(name) == env_values.get(name))
    if not removed:
        return
    for name in removed:
        del env_block[name]
    settings["env"] = env_block
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"Removed legacy TeleClaude MCP credentials from {settings_path}: {', '.join(removed)}")


def _ensure_json_mcp_servers(
    settings_path: Path,
    label: str,
    *,
    managed_mcp_names: set[str],
) -> None:
    """Remove TeleClaude-managed MCP entries from a JSON agent settings file."""
    settings = _load_user_json_or_refuse(settings_path, label=label)
    mcp_servers = _optional_object(settings, "mcpServers", label=label)

    changed = _prune_managed_mcp_servers(mcp_servers, managed_mcp_names)

    if changed:
        settings["mcpServers"] = mcp_servers
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"{label} MCP servers updated in {settings_path}")
    else:
        print(f"{label} MCP servers already configured in {settings_path}")


def _prune_managed_mcp_servers(
    mcp_servers: dict[str, object],
    managed_mcp_names: set[str],
) -> bool:
    """Remove TeleClaude-managed MCP entries; the daemon-owned runtime serves them."""
    changed = False
    for name in sorted(managed_mcp_names):
        if name in mcp_servers:
            del mcp_servers[name]
            changed = True
    return changed


def configure_claude(repo_root: Path) -> None:
    """Configure Claude Code hooks."""
    repo_root = resolve_project_root(repo_root)
    managed_mcp_names = _load_managed_mcp_server_names(repo_root)
    settings_path = Path.home() / ".claude" / "settings.json"
    _optional_object(_load_user_json_or_refuse(settings_path, label="Claude"), "env", label="Claude settings")
    _optional_object(
        _load_user_json_or_refuse(Path.home() / ".claude.json", label="Claude"), "mcpServers", label="Claude"
    )
    _configure_json_agent_hooks(
        repo_root,
        "claude",
        settings_path,
        _claude_hook_map,
    )
    _purge_legacy_mcp_env(settings_path, repo_root)
    _ensure_json_mcp_servers(
        Path.home() / ".claude.json",
        "Claude",
        managed_mcp_names=managed_mcp_names,
    )


def configure_agy(repo_root: Path) -> None:
    """Configure Antigravity CLI (agy) hooks, settings, and MCP."""
    repo_root = resolve_project_root(repo_root)
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    if not receiver_script.exists():
        print(f"Warning: Antigravity receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)

    agy_dir = Path.home() / ".gemini" / "antigravity-cli"
    agy_dir.mkdir(parents=True, exist_ok=True)

    mcp_config_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
    mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_config = _load_user_json_or_blank_or_refuse(mcp_config_path, label="Antigravity MCP")
    existing_mcp_servers = _optional_object(mcp_config, "mcpServers", label="Antigravity MCP")
    managed_mcp_names = _load_managed_mcp_server_names(repo_root)

    # 1. Merge static settings overrides into ~/.gemini/antigravity-cli/settings.json
    settings_path = agy_dir / "settings.json"
    settings = _load_user_json_or_refuse(settings_path, label="Antigravity")
    overrides = _load_settings_overrides("gemini")
    if overrides:
        settings = _deep_merge(settings, overrides)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"Antigravity settings configured in {settings_path}")

    # 2. Removes TeleClaude-managed entries from Antigravity's shared global MCP config.
    changed = _prune_managed_mcp_servers(existing_mcp_servers, managed_mcp_names)

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

    declared_events = _registered_hook_events(AGY_AGENT)

    def command_handler(event: str) -> dict[str, str]:
        return {
            HOOK_TYPE_KEY: HOOK_COMMAND_TYPE,
            HOOK_COMMAND_KEY: _build_hook_command(receiver_invocation, AGY_AGENT, event),
        }

    teleclaude_hooks: dict[str, object] = {}
    for event_name in declared_events:
        if event_name == "PreToolUse":
            teleclaude_hooks[event_name] = [{MATCHER_KEY: MATCHER_ALL, HOOKS_KEY: [command_handler(event_name)]}]
        else:
            teleclaude_hooks[event_name] = [command_handler(event_name)]

    hooks_data["teleclaude"] = teleclaude_hooks

    with open(hooks_path, "w") as f:
        json.dump(hooks_data, f, indent=2)
    print(f"Antigravity hooks configured in {hooks_path}")


def configure_codex(
    repo_root: Path,
) -> None:
    """Configure native Codex hooks and settings."""
    repo_root = resolve_project_root(repo_root)
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

    _optional_object(config, "mcp_servers", label="Codex config")
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

    managed_mcp_names = _load_managed_mcp_server_names(repo_root)
    if managed_mcp_names or "mcp_servers" in config:
        mcp = _optional_object(config, "mcp_servers", label="Codex config")
        _prune_managed_mcp_servers(mcp, managed_mcp_names)
        mcp.pop("teleclaude", None)
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
    project_env = repo_root / ConfigFileName.ENV
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
    repo_root = resolve_project_root(Path(__file__).resolve().parents[2])
    print(f"Configuring agent CLIs from repo: {repo_root}")

    install_agent_wrapper(repo_root, "git")
    install_agent_wrapper(repo_root, "teleclaude-shell")
    install_shell_environment()
    install_env_symlink(repo_root)
    configure_claude(repo_root)
    configure_agy(repo_root)
    configure_codex(repo_root)
    _configure_dsh(repo_root)


if __name__ == MAIN_MODULE:
    main()
