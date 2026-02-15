"""Contract tests to ensure code matches authoritative specifications."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from teleclaude.cli.telec import TelecCommand
from teleclaude.core.events import AgentHookEvents
from teleclaude.mcp_server import ToolName

REPO_ROOT = Path(__file__).resolve().parents[2]


def extract_yaml_from_md(file_path: Path) -> dict:
    """Extract the first YAML code block from a markdown file."""
    content = file_path.read_text(encoding="utf-8")
    # Use triple-quoted string to avoid literal backtick issues in regex
    match = re.search(r"```yaml\n(.*?)\n```", content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML block found in {file_path}")
    return yaml.safe_load(match.group(1))


def test_cli_surface_contract():
    """Verify that TelecCommand enum matches telec-cli-surface.md."""
    spec_path = REPO_ROOT / "docs/project/spec/telec-cli-surface.md"
    spec = extract_yaml_from_md(spec_path)

    spec_subcommands = set(spec.get("subcommands", {}).keys())
    enum_subcommands = {cmd.value for cmd in TelecCommand}

    # Ensure all enum commands are in the spec
    assert enum_subcommands.issubset(spec_subcommands), (
        f"Missing commands in spec: {enum_subcommands - spec_subcommands}"
    )


def test_mcp_tool_surface_contract():
    """Verify that ToolName enum matches mcp-tool-surface.md."""
    spec_path = REPO_ROOT / "docs/project/spec/mcp-tool-surface.md"
    spec = extract_yaml_from_md(spec_path)

    spec_tools = set(spec.get("tools", {}).keys())
    enum_tools = {t.value for t in ToolName}

    # Check for missing or renamed tools
    assert enum_tools == spec_tools, f"Tool mismatch! Diff: {enum_tools ^ spec_tools}"


def test_event_vocabulary_contract():
    """Verify that internal event types match event-vocabulary.md."""
    spec_path = REPO_ROOT / "docs/project/spec/event-vocabulary.md"
    spec = extract_yaml_from_md(spec_path)

    # Check standard events
    spec_standard = set(spec.get("standard_events", []))
    known_standard = {
        "session_started",
        "session_closed",
        "session_updated",
        "agent_event",
        "agent_activity",
        "error",
        "system_command",
    }
    assert spec_standard == known_standard

    # Check agent hook events
    spec_hooks = set(spec.get("agent_hook_events", []))
    known_hooks = set(AgentHookEvents.RECEIVER_HANDLED)
    assert known_hooks.issubset(spec_hooks)


def test_config_contract():
    """Verify that core config keys are documented."""
    spec_path = REPO_ROOT / "docs/project/spec/teleclaude-config.md"
    spec = extract_yaml_from_md(spec_path)

    keys = spec.get("config_keys", {})
    required = {"computer", "agents", "redis", "people", "jobs"}
    assert set(keys.keys()) == required
