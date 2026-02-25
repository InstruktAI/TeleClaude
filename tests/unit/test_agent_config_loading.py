from unittest.mock import patch

import pytest

from teleclaude.config import _build_config


@pytest.fixture
def mock_agent_protocol():
    return {
        "test_agent": {
            "binary": "test_bin",
            "profiles": {"default": ""},
            "session_dir": "/tmp",
            "log_pattern": "*.log",
            "model_flags": {},
            "exec_subcommand": "exec",
            "interactive_flag": "-i",
            "non_interactive_flag": "-p",
            "resume_template": "resume",
            "continue_template": "continue",
        }
    }


@patch("teleclaude.config.resolve_agent_binary", return_value="test_bin")
@patch("teleclaude.config.resolve_tmux_binary", return_value="tmux")
def test_agent_config_loading_defaults(mock_tmux, mock_binary, mock_agent_protocol):
    with patch("teleclaude.constants.AGENT_PROTOCOL", mock_agent_protocol):
        raw_config = {
            "database": {"path": ":memory:"},
            "computer": {
                "name": "test",
                "user": "test",
                "role": "test",
                "timezone": "UTC",
                "default_working_dir": ".",
                "help_desk_dir": ".",
                "is_master": False,
                "trusted_dirs": [],
                "host": None,
            },
            "polling": {"directory_check_interval": 10},
            "redis": {"enabled": False, "url": "redis://localhost", "password": None},
            "telegram": {"trusted_bots": []},
            "ui": {"animations_enabled": False, "animations_periodic_interval": 60},
            "agents": {},  # No override
        }

        config = _build_config(raw_config)
        agent = config.agents["test_agent"]
        assert agent.enabled is True
        assert agent.strengths == ""
        assert agent.avoid == ""


@patch("teleclaude.config.resolve_agent_binary", return_value="test_bin")
@patch("teleclaude.config.resolve_tmux_binary", return_value="tmux")
def test_agent_config_loading_requires_agents_section(mock_tmux, mock_binary, mock_agent_protocol):
    with patch("teleclaude.constants.AGENT_PROTOCOL", mock_agent_protocol):
        raw_config = {
            "database": {"path": ":memory:"},
            "computer": {
                "name": "test",
                "user": "test",
                "role": "test",
                "timezone": "UTC",
                "default_working_dir": ".",
                "help_desk_dir": ".",
                "is_master": False,
                "trusted_dirs": [],
                "host": None,
            },
            "polling": {"directory_check_interval": 10},
            "redis": {"enabled": False, "url": "redis://localhost", "password": None},
            "telegram": {"trusted_bots": []},
            "ui": {"animations_enabled": False, "animations_periodic_interval": 60},
        }

        with pytest.raises(ValueError, match="missing required key `agents`"):
            _build_config(raw_config)


@patch("teleclaude.config.resolve_agent_binary", return_value="test_bin")
@patch("teleclaude.config.resolve_tmux_binary", return_value="tmux")
def test_agent_config_loading_overrides(mock_tmux, mock_binary, mock_agent_protocol):
    with patch("teleclaude.constants.AGENT_PROTOCOL", mock_agent_protocol):
        raw_config = {
            "database": {"path": ":memory:"},
            "computer": {
                "name": "test",
                "user": "test",
                "role": "test",
                "timezone": "UTC",
                "default_working_dir": ".",
                "help_desk_dir": ".",
                "is_master": False,
                "trusted_dirs": [],
                "host": None,
            },
            "polling": {"directory_check_interval": 10},
            "redis": {"enabled": False, "url": "redis://localhost", "password": None},
            "telegram": {"trusted_bots": []},
            "ui": {"animations_enabled": False, "animations_periodic_interval": 60},
            "agents": {"test_agent": {"enabled": False, "strengths": "Testing", "avoid": "Production"}},
        }

        config = _build_config(raw_config)
        agent = config.agents["test_agent"]
        assert agent.enabled is False
        assert agent.strengths == "Testing"
        assert agent.avoid == "Production"


@patch("teleclaude.config.resolve_agent_binary", return_value="test_bin")
@patch("teleclaude.config.resolve_tmux_binary", return_value="tmux")
def test_agent_config_loading_rejects_unknown_agent_keys(mock_tmux, mock_binary, mock_agent_protocol):
    with patch("teleclaude.constants.AGENT_PROTOCOL", mock_agent_protocol):
        raw_config = {
            "database": {"path": ":memory:"},
            "computer": {
                "name": "test",
                "user": "test",
                "role": "test",
                "timezone": "UTC",
                "default_working_dir": ".",
                "help_desk_dir": ".",
                "is_master": False,
                "trusted_dirs": [],
                "host": None,
            },
            "polling": {"directory_check_interval": 10},
            "redis": {"enabled": False, "url": "redis://localhost", "password": None},
            "telegram": {"trusted_bots": []},
            "ui": {"animations_enabled": False, "animations_periodic_interval": 60},
            "agents": {
                "test_agent": {"enabled": True},
                "ghost_agent": {"enabled": True},
            },
        }

        with pytest.raises(ValueError, match="contains unknown agent keys: ghost_agent"):
            _build_config(raw_config)
