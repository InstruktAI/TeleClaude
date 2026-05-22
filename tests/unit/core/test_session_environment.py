"""Tests for agent session environment assembly."""

from __future__ import annotations

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.config.schema import GlobalConfig
from teleclaude.core.session_environment import build_agent_session_environment


@pytest.mark.unit
def test_build_agent_session_environment_uses_project_env_allow_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    monkeypatch.setattr("teleclaude.core.session_environment.load_global_config", lambda: GlobalConfig())
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "env_allow_list:\n  - OPENAI_API_KEY\n  - GOOGLE_APPLICATION_CREDENTIALS\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELECLAUDE_PROJECT_CONFIG_PATH", str(config_path))

    result = build_agent_session_environment(
        project_path=str(tmp_path),
        platform_env={"OPENAI_VOICE": "alloy"},
        source_env={
            "OPENAI_API_KEY": "agent-openai",
            "GOOGLE_APPLICATION_CREDENTIALS": "/keys/google.json",
            "DATABASE_URL": "not-allowed",
        },
    )

    assert result == snapshot


@pytest.mark.unit
def test_build_agent_session_environment_merges_global_and_project_env_allow_lists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    monkeypatch.setattr(
        "teleclaude.core.session_environment.load_global_config",
        lambda: GlobalConfig(env_allow_list=["GLOBAL_TOKEN", "OPENAI_API_KEY"]),
    )
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "env_allow_list:\n  - PROJECT_TOKEN\n  - OPENAI_API_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELECLAUDE_PROJECT_CONFIG_PATH", str(config_path))

    result = build_agent_session_environment(
        project_path=str(tmp_path),
        source_env={
            "GLOBAL_TOKEN": "global",
            "PROJECT_TOKEN": "project",
            "OPENAI_API_KEY": "shared",
            "DATABASE_URL": "not-allowed",
        },
    )

    assert result == snapshot


@pytest.mark.unit
def test_build_agent_session_environment_uses_global_env_allow_list_without_project_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "teleclaude.core.session_environment.load_global_config",
        lambda: GlobalConfig(env_allow_list=["OPENAI_API_KEY"]),
    )
    result = build_agent_session_environment(
        project_path=str(tmp_path),
        platform_env={"MACOS_VOICE": "Samantha"},
        source_env={"OPENAI_API_KEY": "allowed", "DATABASE_URL": "not-allowed"},
    )

    assert result == {"OPENAI_API_KEY": "allowed", "MACOS_VOICE": "Samantha"}
