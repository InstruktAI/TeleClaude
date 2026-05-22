"""Tests for agent session environment assembly."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.session_environment import build_agent_session_environment


@pytest.mark.unit
def test_build_agent_session_environment_uses_project_env_allow_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    assert result == {
        "OPENAI_API_KEY": "agent-openai",
        "GOOGLE_APPLICATION_CREDENTIALS": "/keys/google.json",
        "OPENAI_VOICE": "alloy",
    }


@pytest.mark.unit
def test_build_agent_session_environment_ignores_missing_project_config(tmp_path: Path) -> None:
    result = build_agent_session_environment(
        project_path=str(tmp_path),
        platform_env={"MACOS_VOICE": "Samantha"},
        source_env={"OPENAI_API_KEY": "not-allowed"},
    )

    assert result == {"MACOS_VOICE": "Samantha"}
