from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.config import AgentConfig
from teleclaude.core.next_machine.core import compose_agent_guidance


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.clear_expired_agent_availability = AsyncMock()
    return db


@pytest.fixture
def mock_config():
    with patch("teleclaude.core.next_machine.core.app_config") as mock:
        mock.agents = {
            "claude": AgentConfig(
                binary="claude",
                profiles={},
                session_dir="",
                log_pattern="",
                model_flags={},
                exec_subcommand="",
                interactive_flag="",
                non_interactive_flag="",
                resume_template="",
                enabled=True,
                strengths="Smart",
                avoid="Dumb",
            ),
            "gemini": AgentConfig(
                binary="gemini",
                profiles={},
                session_dir="",
                log_pattern="",
                model_flags={},
                exec_subcommand="",
                interactive_flag="",
                non_interactive_flag="",
                resume_template="",
                enabled=True,
                strengths="Fast",
                avoid="Slow",
            ),
            "codex": AgentConfig(
                binary="codex",
                profiles={},
                session_dir="",
                log_pattern="",
                model_flags={},
                exec_subcommand="",
                interactive_flag="",
                non_interactive_flag="",
                resume_template="",
                enabled=False,
                strengths="Code",
                avoid="Prose",
            ),
        }
        yield mock


async def test_compose_guidance_all_available(mock_db, mock_config):
    mock_db.get_agent_availability.side_effect = lambda agent: {"available": True, "status": "available"}

    guidance = await compose_agent_guidance(mock_db)

    assert "AGENT SELECTION GUIDANCE:" in guidance
    assert "- CLAUDE:" in guidance
    assert "Strengths: Smart" in guidance
    assert "Avoid: Dumb" in guidance
    assert "- GEMINI:" in guidance
    assert "Strengths: Fast" in guidance
    assert "- CODEX" not in guidance  # Disabled
    assert "THINKING MODES:" in guidance


async def test_compose_guidance_agent_degraded(mock_db, mock_config):
    def get_avail(agent):
        if agent == "claude":
            return {"available": True, "status": "degraded", "reason": "Rate limited"}
        return {"available": True, "status": "available"}

    mock_db.get_agent_availability.side_effect = get_avail

    guidance = await compose_agent_guidance(mock_db)

    assert "- CLAUDE [DEGRADED: Rate limited]:" in guidance
    assert "- GEMINI:" in guidance


async def test_compose_guidance_agent_unavailable(mock_db, mock_config):
    def get_avail(agent):
        if agent == "claude":
            return {"available": False, "status": "unavailable"}
        return {"available": True, "status": "available"}

    mock_db.get_agent_availability.side_effect = get_avail

    guidance = await compose_agent_guidance(mock_db)

    assert "- CLAUDE" not in guidance
    assert "- GEMINI:" in guidance


async def test_compose_guidance_no_agents(mock_db, mock_config):
    # Disable all agents in config
    mock_config.agents = {
        "claude": AgentConfig(
            binary="claude",
            profiles={},
            session_dir="",
            log_pattern="",
            model_flags={},
            exec_subcommand="",
            interactive_flag="",
            non_interactive_flag="",
            resume_template="",
            enabled=False,
        )
    }

    with pytest.raises(RuntimeError, match="No agents are currently enabled and available"):
        await compose_agent_guidance(mock_db)


async def test_compose_guidance_all_runtime_unavailable(mock_db, mock_config):
    # Agents are enabled in config but unavailable in DB
    mock_db.get_agent_availability.return_value = {"status": "unavailable"}

    # CURRENTLY this will FAIL to raise RuntimeError (it will return empty guidance)
    # We want it to raise RuntimeError
    with pytest.raises(RuntimeError, match="No agents are currently enabled and available"):
        await compose_agent_guidance(mock_db)
