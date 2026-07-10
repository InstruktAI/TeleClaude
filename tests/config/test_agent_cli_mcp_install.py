"""Installer MCP publication tests."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

import teleclaude.install.configure_agent_cli as installer

pytestmark = pytest.mark.functional

BASE_COMMAND = "base-command"
BASE_SECRET = "base-secret"
FIRECRAWL_SECRET = "firecrawl-secret"
FIRECRAWL_SERVER = "firecrawl"
LITERAL_COMMAND = "literal-command"
LITERAL_ENV_VALUE = "literal-value"
LITERAL_ENV_SERVER = "literal-env"
LITERAL_ARG = "literal-arg"
LOCAL_COMMAND = "local-command"
LOCAL_SECRET = "local-secret"
LOCAL_SERVER = "local-only"
MANAGED_SERVER = "managed-only"
OMI_SECRET = "omi-secret"
OMI_SERVER = "omi-memory"
OMI_URL = "https://api.omi.me/v1/mcp/sse"
OVERRIDDEN_SERVER = "overridden"


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
                MANAGED_SERVER: {
                    "command": "managed-command",
                    "args": ["managed-arg"],
                },
                FIRECRAWL_SERVER: {
                    "command": "npx",
                    "args": ["-y", "firecrawl-mcp"],
                    "env": {"FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}"},
                    "nativePublish": True,
                },
                LITERAL_ENV_SERVER: {
                    "command": LITERAL_COMMAND,
                    "args": [LITERAL_ARG],
                    "env": {"LITERAL_VALUE": LITERAL_ENV_VALUE},
                    "nativePublish": True,
                },
                OVERRIDDEN_SERVER: {
                    "command": BASE_COMMAND,
                    "args": ["base-arg"],
                    "env": {"BASE_VAR": "$BASE_VAR"},
                    "nativePublish": True,
                },
            }
        },
    )
    _write_json(
        repo / "mcp.local.json",
        {
            "mcpServers": {
                LOCAL_SERVER: {"command": LOCAL_COMMAND, "args": ["local-arg"], "nativePublish": True},
                OMI_SERVER: {
                    "type": "http",
                    "url": OMI_URL,
                    "headers": {
                        "Authorization": "Bearer ${OMI_API_KEY}",
                    },
                    "nativePublish": True,
                },
                OVERRIDDEN_SERVER: {
                    "args": ["local-arg"],
                    "env": {"LOCAL_VAR": "${LOCAL_VAR}"},
                },
            }
        },
    )
    return repo


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_installer_publishes_only_native_publish_entries_to_global_agent_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
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
    baseline_before = _digest(repo / "mcp.json")
    local_before = _digest(repo / "mcp.local.json")
    (home / ".gemini" / "config").mkdir(parents=True)
    (home / ".gemini" / "config" / "mcp_config.json").write_text("", encoding="utf-8")

    installer.configure_claude(repo)
    installer.configure_agy(repo)
    installer.configure_codex(repo)

    assert _digest(repo / "mcp.json") == baseline_before
    assert _digest(repo / "mcp.local.json") == local_before

    claude_mcp = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    agy_mcp = json.loads((home / ".gemini" / "config" / "mcp_config.json").read_text(encoding="utf-8"))
    codex_config = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))

    assert {
        "claude": claude_mcp["mcpServers"],
        "antigravity": agy_mcp["mcpServers"],
        "codex": codex_config["mcp_servers"],
    } == snapshot(name="mcp_configs")

    claude_settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert claude_settings["env"] == snapshot(name="claude_env")
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
    settings_before = _digest(settings_path)

    with pytest.raises(RuntimeError):
        installer.configure_claude(_make_repo(tmp_path))

    assert _digest(settings_path) == settings_before
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
    claude_mcp_before = _digest(claude_mcp_path)

    with pytest.raises(RuntimeError):
        installer.configure_claude(repo)

    assert _digest(claude_mcp_path) == claude_mcp_before
    assert not (home / ".claude" / "settings.json").exists()

    claude_mcp_path.unlink()
    agy_mcp_path = home / ".gemini" / "config" / "mcp_config.json"
    _write_json(agy_mcp_path, {"mcpServers": []})
    agy_mcp_before = _digest(agy_mcp_path)

    with pytest.raises(RuntimeError):
        installer.configure_agy(repo)

    assert _digest(agy_mcp_path) == agy_mcp_before
    assert not (home / ".gemini" / "antigravity-cli" / "settings.json").exists()

    agy_mcp_path.unlink()
    codex_config_path = home / ".codex" / "config.toml"
    codex_config_path.parent.mkdir(parents=True)
    codex_config_path.write_text("mcp_servers = []\n", encoding="utf-8")
    codex_config_before = _digest(codex_config_path)

    with pytest.raises(RuntimeError):
        installer.configure_codex(repo)

    assert _digest(codex_config_path) == codex_config_before
    assert not (home / ".codex" / "hooks.json").exists()
