import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from teleclaude.config import AgentConfig
from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.helpers import agent_cli
from teleclaude.helpers.agent_types import AgentName


def _write_agent_availability_db(
    db_path: str,
    rows: list[tuple[str, int, str | None]],
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_availability (
                agent TEXT PRIMARY KEY,
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT
            )
            """
        )
        conn.executemany(
            "INSERT OR REPLACE INTO agent_availability(agent, available, unavailable_until, reason) VALUES (?, ?, ?, ?)",
            [(agent, available, unavailable_until, "test") for agent, available, unavailable_until in rows],
        )
        conn.commit()


def _set_binary_map(monkeypatch: pytest.MonkeyPatch, available: set[str]) -> None:
    monkeypatch.setattr(agent_cli, "resolve_agent_binary", lambda name: name)
    monkeypatch.setattr(
        agent_cli.shutil,
        "which",
        lambda binary: f"/usr/bin/{binary}" if binary in available else None,
    )


def _mock_app_config_agents(monkeypatch: pytest.MonkeyPatch, disabled: set[str] = None) -> None:
    disabled = disabled or set()
    mock_agents = {}
    for name in ["claude", "gemini", "codex"]:
        mock_agents[name] = AgentConfig(
            binary=name,
            profiles={},
            session_dir="",
            log_pattern="",
            model_flags={},
            exec_subcommand="",
            interactive_flag="",
            non_interactive_flag="",
            resume_template="",
            enabled=(name not in disabled),
        )
    monkeypatch.setattr(agent_cli.app_config, "agents", mock_agents)


def test_pick_agent_prefers_first_db_available(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})
    _mock_app_config_agents(monkeypatch)

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("claude", 0, future),  # unavailable
            ("codex", 1, None),  # available
        ],
    )

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CODEX


def test_pick_agent_rejects_unavailable_preferred(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})
    _mock_app_config_agents(monkeypatch)

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("codex", 0, future),
        ],
    )

    with pytest.raises(SystemExit, match="marked unavailable"):
        agent_cli._pick_agent(AgentName.CODEX)


def test_pick_agent_treats_expired_unavailability_as_available(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})
    _mock_app_config_agents(monkeypatch)

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("claude", 0, past),  # expired unavailability
        ],
    )

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CLAUDE


def test_pick_agent_fails_when_no_binary_and_db_available(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, set())
    _mock_app_config_agents(monkeypatch)

    with pytest.raises(SystemExit, match="no available agent CLI found"):
        agent_cli._pick_agent(None)


def test_pick_agent_skips_degraded(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})
    _mock_app_config_agents(monkeypatch)

    with sqlite3.connect(str(tmp_path / "teleclaude.db")) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_availability (
                agent TEXT PRIMARY KEY,
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO agent_availability(agent, available, unavailable_until, reason) VALUES (?, ?, ?, ?)",
            ("claude", 1, None, "degraded:manual"),
        )
        conn.commit()

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CODEX


def test_pick_agent_rejects_degraded_preferred(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})
    _mock_app_config_agents(monkeypatch)

    with sqlite3.connect(str(tmp_path / "teleclaude.db")) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_availability (
                agent TEXT PRIMARY KEY,
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO agent_availability(agent, available, unavailable_until, reason) VALUES (?, ?, ?, ?)",
            ("codex", 1, None, "degraded:test"),
        )
        conn.commit()

    with pytest.raises(SystemExit, match="unavailable or degraded"):
        agent_cli._pick_agent(AgentName.CODEX)


def test_pick_agent_respects_config_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    # Disable claude in config
    _mock_app_config_agents(monkeypatch, disabled={"claude"})

    # Even if DB says claude is available, it should be skipped because of config
    _write_agent_availability_db(
        str(tmp_path / "teleclaude.db"),
        [
            ("claude", 1, None),
            ("gemini", 1, None),
        ],
    )

    selected = agent_cli._pick_agent(None)
    assert selected == AgentName.CODEX


def test_pick_agent_preferred_config_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(agent_cli, "_REPO_ROOT", tmp_path)
    _set_binary_map(monkeypatch, {"claude", "codex", "gemini"})

    # Disable claude in config
    _mock_app_config_agents(monkeypatch, disabled={"claude"})

    with pytest.raises(SystemExit, match="disabled in config.yml"):
        agent_cli._pick_agent(AgentName.CLAUDE)


def test_agent_protocol_blocks_mcp_for_interactive_profiles() -> None:
    claude_profiles = AGENT_PROTOCOL["claude"]["profiles"]
    assert isinstance(claude_profiles, dict)
    assert "--strict-mcp-config" in claude_profiles["default"]
    assert "--strict-mcp-config" in claude_profiles["restricted"]
    assert '"enabledMcpjsonServers": []' in claude_profiles["default"]
    assert '"enabledMcpjsonServers": []' in claude_profiles["restricted"]

    gemini_profiles = AGENT_PROTOCOL["gemini"]["profiles"]
    assert isinstance(gemini_profiles, dict)
    assert "--allowed-mcp-server-names _none_" in gemini_profiles["default"]
    assert "--allowed-mcp-server-names _none_" in gemini_profiles["restricted"]


def test_job_spec_blocks_mcp_for_agent_jobs() -> None:
    claude_flags = str(agent_cli._JOB_SPEC["claude"]["flags"])
    assert "--strict-mcp-config" in claude_flags
    assert '"enabledMcpjsonServers": []' in claude_flags

    gemini_flags = str(agent_cli._JOB_SPEC["gemini"]["flags"])
    assert "--allowed-mcp-server-names _none_" in gemini_flags
