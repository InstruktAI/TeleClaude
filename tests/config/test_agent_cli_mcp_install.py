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
BASE_WRAPPED_ARGS = [
    "-lc",
    (
        'source "$HOME/.teleclaude/.env"; [ -n "${BASE_VAR:-}" ] || { echo "Missing BASE_VAR" >&2; exit 1; }; '
        '[ -n "${LOCAL_VAR:-}" ] || { echo "Missing LOCAL_VAR" >&2; exit 1; }; exec env BASE_VAR="${BASE_VAR}" '
        'LOCAL_VAR="${LOCAL_VAR}" base-command local-arg'
    ),
]
FIRECRAWL_COMMAND = "bash"
FIRECRAWL_ARGS = [
    "-lc",
    (
        'source "$HOME/.teleclaude/.env"; [ -n "${FIRECRAWL_API_KEY:-}" ] || { echo '
        '"Missing FIRECRAWL_API_KEY" >&2; exit 1; }; exec env FIRECRAWL_API_KEY="${FIRECRAWL_API_KEY}" '
        "npx -y firecrawl-mcp"
    ),
]
FIRECRAWL_SECRET = "firecrawl-secret"
FIRECRAWL_SERVER = "firecrawl"
LITERAL_COMMAND = "literal-command"
LITERAL_ENV_VALUE = "literal-value"
LITERAL_ENV_SERVER = "literal-env"
LITERAL_ARG = "literal-arg"
LOCAL_COMMAND = "local-command"
LOCAL_SECRET = "local-secret"
LOCAL_SERVER = "local-only"
OMI_REMOTE_ARGS = [
    "-lc",
    (
        'source "$HOME/.teleclaude/.env"; [ -n "${OMI_API_KEY:-}" ] || { echo '
        '"Missing OMI_API_KEY" >&2; exit 1; }; exec env OMI_API_KEY="${OMI_API_KEY}" npx -y mcp-remote@latest '
        "https://api.omi.me/v1/mcp/sse --header 'Authorization: Bearer ${OMI_API_KEY}' --transport http-only"
    ),
]
OMI_SECRET = "omi-secret"
OMI_SERVER = "omi-memory"
OMI_URL = "https://api.omi.me/v1/mcp/sse"
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
                    "command": "npx",
                    "args": ["-y", "firecrawl-mcp"],
                    "env": {"FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}"},
                },
                LITERAL_ENV_SERVER: {
                    "command": LITERAL_COMMAND,
                    "args": [LITERAL_ARG],
                    "env": {"LITERAL_VALUE": LITERAL_ENV_VALUE},
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
                OMI_SERVER: {
                    "type": "http",
                    "url": OMI_URL,
                    "headers": {
                        "Authorization": "Bearer ${OMI_API_KEY}",
                    },
                },
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
                f"OMI_API_KEY={OMI_SECRET}",
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
        assert mcp_servers[FIRECRAWL_SERVER]["args"] == FIRECRAWL_ARGS
        assert "env" not in mcp_servers[FIRECRAWL_SERVER]
        assert mcp_servers[LITERAL_ENV_SERVER]["command"] == LITERAL_COMMAND
        assert mcp_servers[LITERAL_ENV_SERVER]["args"] == [LITERAL_ARG]
        assert mcp_servers[LITERAL_ENV_SERVER]["env"] == {"LITERAL_VALUE": LITERAL_ENV_VALUE}
        assert mcp_servers[LOCAL_SERVER]["command"] == LOCAL_COMMAND
        assert mcp_servers[OMI_SERVER]["command"] == FIRECRAWL_COMMAND
        assert mcp_servers[OMI_SERVER]["args"] == OMI_REMOTE_ARGS
        assert mcp_servers[OVERRIDDEN_SERVER]["command"] == FIRECRAWL_COMMAND
        assert mcp_servers[OVERRIDDEN_SERVER]["args"] == BASE_WRAPPED_ARGS
        assert "env" not in mcp_servers[OVERRIDDEN_SERVER]

    assert codex_config["mcp_servers"][FIRECRAWL_SERVER]["type"] == STDIO_TYPE
    assert codex_config["mcp_servers"][LITERAL_ENV_SERVER]["type"] == STDIO_TYPE
    assert codex_config["mcp_servers"][LOCAL_SERVER]["type"] == STDIO_TYPE
    assert codex_config["mcp_servers"][OMI_SERVER]["type"] == STDIO_TYPE

    claude_settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert claude_settings["env"]["FIRECRAWL_API_KEY"] == FIRECRAWL_SECRET
    assert claude_settings["env"]["BASE_VAR"] == BASE_SECRET
    assert claude_settings["env"]["LOCAL_VAR"] == LOCAL_SECRET
    assert claude_settings["env"]["OMI_API_KEY"] == OMI_SECRET
    assert not (home / ".gemini" / "settings.json").exists()


def test_installer_rejects_malformed_existing_claude_env_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    env_path = tmp_path / ".teleclaude" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(f"FIRECRAWL_API_KEY={FIRECRAWL_SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(installer, "ENV_PATH", env_path)

    settings_path = home / ".claude" / "settings.json"
    _write_json(settings_path, {"env": []})
    settings_before = settings_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError):
        installer.configure_claude(_make_repo(tmp_path))

    assert settings_path.read_text(encoding="utf-8") == settings_before
    assert not (home / ".claude.json").exists()


def test_installer_rejects_malformed_existing_mcp_blocks_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    repo = _make_repo(tmp_path)

    claude_mcp_path = home / ".claude.json"
    _write_json(claude_mcp_path, {"mcpServers": []})
    claude_mcp_before = claude_mcp_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError):
        installer.configure_claude(repo)

    assert claude_mcp_path.read_text(encoding="utf-8") == claude_mcp_before
    assert not (home / ".claude" / "settings.json").exists()

    claude_mcp_path.unlink()
    agy_mcp_path = home / ".gemini" / "config" / "mcp_config.json"
    _write_json(agy_mcp_path, {"mcpServers": []})
    agy_mcp_before = agy_mcp_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError):
        installer.configure_agy(repo)

    assert agy_mcp_path.read_text(encoding="utf-8") == agy_mcp_before
    assert not (home / ".gemini" / "antigravity-cli" / "settings.json").exists()

    agy_mcp_path.unlink()
    codex_config_path = home / ".codex" / "config.toml"
    codex_config_path.parent.mkdir(parents=True)
    codex_config_path.write_text("mcp_servers = []\n", encoding="utf-8")
    codex_config_before = codex_config_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError):
        installer.configure_codex(repo)

    assert codex_config_path.read_text(encoding="utf-8") == codex_config_before
    assert not (home / ".codex" / "hooks.json").exists()
