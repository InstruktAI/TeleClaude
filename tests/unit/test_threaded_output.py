import json
from datetime import datetime, timezone
from pathlib import Path

from teleclaude.config import (
    Config,
    DiscordConfig,
    ExperimentConfig,
)
from teleclaude.core.agents import AgentName
from teleclaude.utils.markdown import _required_markdown_closers, telegramify_markdown
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)


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
    assert '🔧 **`test_tool {"arg": 1}`**' in result
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

    # since_timestamp = ts2 should return only the third entry with timestamp prefix
    result, last_ts = render_agent_output(str(transcript_path), AgentName.CLAUDE, since_timestamp=dt2)
    assert result == "[10:00:02] Third"
    assert last_ts.isoformat().startswith("2025-01-01T10:00:02")


def test_rotation_fallback_render_agent_output_with_no_user_boundary(tmp_path):
    """If rotated transcript has no user entries, render from start as fallback."""
    transcript_path = tmp_path / "rotated.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:00.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "After rotate A"}]},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:01.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "After rotate B"}]},
                    }
                ),
            ]
        )
    )

    dt_after = datetime(2025, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
    result, _last_ts = render_agent_output(str(transcript_path), AgentName.CLAUDE, since_timestamp=dt_after)
    assert result is not None
    assert "After rotate A" in result
    assert "After rotate B" in result


def test_rotation_fallback_get_assistant_messages_with_no_user_boundary(tmp_path):
    """Cursor misses should still return assistant messages for rotated files."""
    transcript_path = tmp_path / "rotated_messages.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:00.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Chunk A"}]},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:01.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Chunk B"}]},
                    }
                ),
            ]
        )
    )

    dt_after = datetime(2025, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
    messages = get_assistant_messages_since(str(transcript_path), AgentName.CLAUDE, since_timestamp=dt_after)
    assert len(messages) == 2


def test_no_rotation_fallback_when_user_boundary_exists(tmp_path):
    """When a user boundary exists, no fallback should occur for stale cursors."""
    transcript_path = tmp_path / "not_rotated.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:00.000Z",
                        "type": "user",
                        "message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:01.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Reply"}]},
                    }
                ),
            ]
        )
    )

    dt_after = datetime(2025, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
    messages = get_assistant_messages_since(str(transcript_path), AgentName.CLAUDE, since_timestamp=dt_after)
    assert messages == []


def test_rotation_fallback_render_clean_output_with_no_user_boundary(tmp_path):
    """Clean renderer should also fallback for rotated files without user entries."""
    transcript_path = tmp_path / "rotated_clean.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:00.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Clean A"}]},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2025-01-01T10:00:01.000Z",
                        "type": "assistant",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Clean B"}]},
                    }
                ),
            ]
        )
    )

    dt_after = datetime(2025, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
    result, _last_ts = render_clean_agent_output(str(transcript_path), AgentName.CLAUDE, since_timestamp=dt_after)
    assert result is not None
    assert "Clean A" in result
    assert "Clean B" in result


def test_real_gemini_artifact_returns_single_message_with_multiple_blocks():
    fixture = Path("tests/fixtures/transcripts/gemini_real_incremental_snapshot.json")
    assert fixture.exists(), "Expected real Gemini artifact fixture to exist"

    messages = get_assistant_messages_since(str(fixture), AgentName.GEMINI)
    assert len(messages) == 1

    block_count = count_renderable_assistant_blocks(str(fixture), AgentName.GEMINI, include_tools=True)
    assert block_count >= 2


def test_real_gemini_artifact_renders_full_output():
    fixture = Path("tests/fixtures/transcripts/gemini_real_incremental_snapshot.json")
    result, _last_ts = render_agent_output(
        str(fixture),
        AgentName.GEMINI,
        include_tools=True,
        include_tool_results=False,
    )
    assert result is not None

    formatted = telegramify_markdown(result, collapse_code_blocks=True)
    assert _required_markdown_closers(formatted) == ""


def test_is_experiment_enabled():
    config = Config(
        database=None,
        computer=None,
        polling=None,
        redis=None,
        telegram=None,
        discord=DiscordConfig(enabled=False, token=None, guild_id=None, help_desk_channel_id=None),
        creds=None,
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


# Heavy fixture tests - comprehensive coverage for real-world Gemini output
# Tests the final turn's content (after last user boundary) which is the actual use case
HEAVY_FIXTURE = Path("tests/fixtures/transcripts/gemini_real_heavy_output_fixture.json")


def test_heavy_fixture_exists():
    """Ensure the heavy Gemini fixture is available for testing."""
    assert HEAVY_FIXTURE.exists(), "Heavy Gemini fixture missing"


def test_heavy_fixture_has_content_after_last_user():
    """Verify the heavy fixture has assistant content in the final turn."""
    messages = get_assistant_messages_since(str(HEAVY_FIXTURE), AgentName.GEMINI)
    assert len(messages) >= 1, "Expected at least 1 assistant message after last user"

    block_count = count_renderable_assistant_blocks(str(HEAVY_FIXTURE), AgentName.GEMINI, include_tools=True)
    assert block_count >= 2, "Expected at least 2 renderable blocks"


def test_heavy_fixture_render_produces_output():
    """Render the heavy fixture's final turn and verify output exists."""
    result, last_ts = render_agent_output(
        str(HEAVY_FIXTURE),
        AgentName.GEMINI,
        include_tools=True,
        include_tool_results=False,
    )
    assert result is not None
    assert len(result) > 1000, "Expected substantial rendered output"
    assert last_ts is not None


def test_heavy_fixture_telegramify_without_collapse():
    """Test telegramify_markdown on heavy content produces balanced markdown."""
    result, _last_ts = render_agent_output(
        str(HEAVY_FIXTURE),
        AgentName.GEMINI,
        include_tools=True,
        include_tool_results=False,
    )
    assert result is not None

    formatted = telegramify_markdown(result, collapse_code_blocks=False)
    closers = _required_markdown_closers(formatted)

    # Spurious || markers from telegramify-markdown are stripped in our wrapper
    assert closers == "", f"Unexpected unclosed entities: {repr(closers)}"


def test_heavy_fixture_clean_render_returns_content():
    """Verify render_clean_agent_output produces output from heavy fixture."""
    result, _last_ts = render_clean_agent_output(str(HEAVY_FIXTURE), AgentName.GEMINI)
    # Clean render should produce content from the heavy fixture
    assert result is not None, "Expected clean render to produce output"
    assert len(result) > 100, "Expected substantial clean render output"


def test_heavy_fixture_with_tools_includes_tool_emoji():
    """Verify render_agent_output includes tool blocks when requested."""
    result, _last_ts = render_agent_output(
        str(HEAVY_FIXTURE),
        AgentName.GEMINI,
        include_tools=True,
        include_tool_results=False,
    )
    assert result is not None
    # Heavy fixture has tool calls, so we expect tool emoji
    assert "🔧" in result, "Expected tool emoji in output with include_tools=True"


def test_heavy_fixture_contains_diverse_content():
    """Verify the fixture has diverse content types for thorough testing."""
    result, _last_ts = render_agent_output(
        str(HEAVY_FIXTURE),
        AgentName.GEMINI,
        include_tools=True,
        include_tool_results=False,
    )
    assert result is not None
    # Check for diverse content markers
    has_thinking = "*" in result  # Italics from thinking blocks
    has_headers = "###" in result or "**" in result  # Bold/headers
    has_tool = "🔧" in result
    has_text = len(result) > 500
    diversity = sum([has_thinking, has_headers, has_tool, has_text])
    assert diversity >= 3, f"Expected diverse content types, got only {diversity}/4"
