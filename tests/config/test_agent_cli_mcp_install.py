"""Installer MCP publication tests."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import teleclaude.install.configure_agent_cli as installer

pytestmark = pytest.mark.functional

BASE_COMMAND = "base-command"
BASE_SECRET = "base-secret"
FIRECRAWL_COMMAND = "bash"
FIRECRAWL_SECRET = "firecrawl-secret"
FIRECRAWL_SERVER = "firecrawl"
LOCAL_COMMAND = "local-command"
LOCAL_SECRET = "local-secret"
LOCAL_SERVER = "local-only"
OVERRIDDEN_SERVER = "overridden"
STDIO_TYPE = "stdio"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    receiver = repo / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True, exist_ok=True)
    receiver.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / "teleclaude.yml").write_text("project_slug: test\n", encoding="utf-8")

    _write_json(
        repo / "mcp.json",
        {
            "mcpServers": {
                FIRECRAWL_SERVER: {
                    "command": FIRECRAWL_COMMAND,
                    "args": [
                        "-lc",
                        'source "$HOME/.teleclaude/.env"; exec env FIRECRAWL_API_KEY="$FIRECRAWL_API_KEY" npx -y firecrawl-mcp',
                    ],
                },
                OVERRIDDEN_SERVER: {
                    "command": BASE_COMMAND,
                    "args": ["base-arg"],
                    "env": {"BASE_VAR": "$BASE_VAR"},
                },
            }
        },
    )
    _write_json(
        repo / "mcp.local.json",
        {
            "mcpServers": {
                LOCAL_SERVER: {"command": LOCAL_COMMAND, "args": ["local-arg"]},
                OVERRIDDEN_SERVER: {
                    "args": ["local-arg"],
                    "env": {"LOCAL_VAR": "${LOCAL_VAR}"},
                },
            }
        },
    )
    return repo


def test_installer_publishes_merged_mcp_inputs_to_global_agent_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    env_path = tmp_path / ".teleclaude" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "\n".join(
            [
                f"FIRECRAWL_API_KEY={FIRECRAWL_SECRET}",
                f"BASE_VAR={BASE_SECRET}",
                f"LOCAL_VAR={LOCAL_SECRET}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(installer, "ENV_PATH", env_path)

    repo = _make_repo(tmp_path)
    baseline_before = (repo / "mcp.json").read_text(encoding="utf-8")
    local_before = (repo / "mcp.local.json").read_text(encoding="utf-8")
    (home / ".gemini" / "config").mkdir(parents=True)
    (home / ".gemini" / "config" / "mcp_config.json").write_text("", encoding="utf-8")

    installer.configure_claude(repo)
    installer.configure_agy(repo)
    installer.configure_codex(repo)

    assert (repo / "mcp.json").read_text(encoding="utf-8") == baseline_before
    assert (repo / "mcp.local.json").read_text(encoding="utf-8") == local_before

    claude_mcp = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    agy_mcp = json.loads((home / ".gemini" / "config" / "mcp_config.json").read_text(encoding="utf-8"))
    codex_config = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    for mcp_servers in (
        claude_mcp["mcpServers"],
        agy_mcp["mcpServers"],
        codex_config["mcp_servers"],
    ):
        assert mcp_servers[FIRECRAWL_SERVER]["command"] == FIRECRAWL_COMMAND
        assert mcp_servers[LOCAL_SERVER]["command"] == LOCAL_COMMAND
        assert mcp_servers[OVERRIDDEN_SERVER]["command"] == BASE_COMMAND
        assert mcp_servers[OVERRIDDEN_SERVER]["args"] == ["local-arg"]
        assert mcp_servers[OVERRIDDEN_SERVER]["env"] == {
            "BASE_VAR": "$BASE_VAR",
            "LOCAL_VAR": "${LOCAL_VAR}",
        }

    assert codex_config["mcp_servers"][FIRECRAWL_SERVER]["type"] == STDIO_TYPE
    assert codex_config["mcp_servers"][LOCAL_SERVER]["type"] == STDIO_TYPE

    claude_settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert claude_settings["env"]["FIRECRAWL_API_KEY"] == FIRECRAWL_SECRET
    assert claude_settings["env"]["BASE_VAR"] == BASE_SECRET
    assert claude_settings["env"]["LOCAL_VAR"] == LOCAL_SECRET
    assert not (home / ".gemini" / "settings.json").exists()
