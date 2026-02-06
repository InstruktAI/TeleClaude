import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from teleclaude.config import (
    ComputerConfig,
    Config,
    DatabaseConfig,
    ExperimentConfig,
    RedisConfig,
    TelegramConfig,
    TerminalConfig,
    UIConfig,
)
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import render_agent_output


def test_render_agent_output_basic(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]},
                    }
                ),
            ]
        )
    )

    result, _ts = render_agent_output(str(transcript_path), AgentName.CLAUDE)
    assert result == "Hi there"


def test_render_agent_output_thinking(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "Let me think..."},
                                {"type": "text", "text": "Hi there"},
                            ],
                        },
                    }
                ),
            ]
        )
    )

    result, _ts = render_agent_output(str(transcript_path), AgentName.CLAUDE)
    assert "*Let me think...*" in result
    assert "Hi there" in result


def test_render_agent_output_exclude_tools(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "tool_use", "name": "test_tool", "input": {"arg": 1}},
                                {"type": "text", "text": "Tool used"},
                            ],
                        },
                    }
                ),
            ]
        )
    )

    result, _ts = render_agent_output(str(transcript_path), AgentName.CLAUDE, include_tools=False)
    assert "test_tool" not in result
    assert "Tool used" in result


def test_render_agent_output_include_tools(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "tool_use", "name": "test_tool", "input": {"arg": 1}},
                                {"type": "text", "text": "Tool used"},
                            ],
                        },
                    }
                ),
            ]
        )
    )

    result, _ts = render_agent_output(str(transcript_path), AgentName.CLAUDE, include_tools=True)
    assert "🔧 **TOOL CALL:** test_tool" in result
    assert "Tool used" in result


def test_render_agent_output_user_boundary(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Old message"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": [{"type": "input_text", "text": "Latest prompt"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "New message"}]},
                    }
                ),
            ]
        )
    )

    result, _ts = render_agent_output(str(transcript_path), AgentName.CLAUDE)
    assert "Old message" not in result
    assert "New message" == result


def test_render_agent_output_delta(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    ts1 = "2025-01-01T10:00:00.000Z"
    ts2 = "2025-01-01T10:00:01.000Z"
    ts3 = "2025-01-01T10:00:02.000Z"

    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": ts1,
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "First"}]},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": ts2,
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Second"}]},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": ts3,
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Third"}]},
                    }
                ),
            ]
        )
    )

    dt2 = datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc)

    # since_timestamp = ts2 should return only "Third"
    result, last_ts = render_agent_output(str(transcript_path), AgentName.CLAUDE, since_timestamp=dt2)
    assert result == "Third"
    assert last_ts.isoformat().startswith("2025-01-01T10:00:02")


def test_is_experiment_enabled():
    config = Config(
        database=None,
        computer=None,
        redis=None,
        telegram=None,
        agents={},
        ui=None,
        terminal=None,
        experiments=[
            ExperimentConfig(name="exp_all"),
            ExperimentConfig(name="exp_gemini", agents=["gemini"]),
        ],
    )

    assert config.is_experiment_enabled("exp_all") is True
    assert config.is_experiment_enabled("exp_all", "gemini") is True
    assert config.is_experiment_enabled("exp_gemini", "gemini") is True
    assert config.is_experiment_enabled("exp_gemini", "claude") is False
    assert config.is_experiment_enabled("non_existent") is False
