import json
import pytest
from pathlib import Path
from teleclaude.utils.transcript import render_stop_turn
from teleclaude.core.agents import AgentName
from teleclaude.config import Config, ExperimentConfig, DatabaseConfig, ComputerConfig, RedisConfig, TelegramConfig, UIConfig, TerminalConfig

def test_render_stop_turn_basic(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]}}),
    ]))
    
    result = render_stop_turn(str(transcript_path), AgentName.CLAUDE)
    assert result == "Hi there"

def test_render_stop_turn_thinking(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "Let me think..."},
            {"type": "text", "text": "Hi there"}
        ]}}),
    ]))
    
    result = render_stop_turn(str(transcript_path), AgentName.CLAUDE)
    assert "*Let me think...*" in result
    assert "Hi there" in result

def test_render_stop_turn_exclude_tools(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "test_tool", "input": {"arg": 1}},
            {"type": "text", "text": "Tool used"}
        ]}}),
    ]))
    
    result = render_stop_turn(str(transcript_path), AgentName.CLAUDE, include_tools=False)
    assert "test_tool" not in result
    assert "Tool used" in result

def test_render_stop_turn_include_tools(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "test_tool", "input": {"arg": 1}},
            {"type": "text", "text": "Tool used"}
        ]}}),
    ]))
    
    result = render_stop_turn(str(transcript_path), AgentName.CLAUDE, include_tools=True)
    assert "🔧 **TOOL CALL:** test_tool" in result
    assert "Tool used" in result

def test_render_stop_turn_user_boundary(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text("\n".join([
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Old message"}]}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "input_text", "text": "Latest prompt"}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "New message"}]}}),
    ]))
    
    result = render_stop_turn(str(transcript_path), AgentName.CLAUDE)
    assert "Old message" not in result
    assert "New message" == result

def test_is_experiment_enabled():
    config = Config(
        database=None, computer=None, redis=None, telegram=None, agents={}, ui=None, terminal=None,
        experiments=[
            ExperimentConfig(name="exp_all"),
            ExperimentConfig(name="exp_gemini", agents=["gemini"]),
        ]
    )
    
    assert config.is_experiment_enabled("exp_all") is True
    assert config.is_experiment_enabled("exp_all", "gemini") is True
    assert config.is_experiment_enabled("exp_gemini", "gemini") is True
    assert config.is_experiment_enabled("exp_gemini", "claude") is False
    assert config.is_experiment_enabled("non_existent") is False