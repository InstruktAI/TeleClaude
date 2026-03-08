"""Unit tests for telec history and memories CLI subcommands."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.cli import telec
from teleclaude.cli.api_client import APIError


# ---------------------------------------------------------------------------
# _handle_history helpers
# ---------------------------------------------------------------------------


def test_handle_history_no_args_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_history([])
    out = capsys.readouterr().out
    assert "history" in out


def test_handle_history_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_history(["--help"])
    out = capsys.readouterr().out
    assert "history" in out


def test_handle_history_unknown_subcommand_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        telec._handle_history(["unknown"])


def test_handle_history_search_no_terms_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        telec._handle_history_search([])


def test_handle_history_search_calls_display_combined_history(capsys: pytest.CaptureFixture[str]) -> None:
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    def fake_display(agents, search_term="", limit=20, computers=None):
        captured["agents"] = agents
        captured["term"] = search_term
        captured["limit"] = limit
        captured["computers"] = computers

    with (
        patch("teleclaude.history.search.parse_agents") as fake_parse,
        patch("teleclaude.history.search.display_combined_history", fake_display),
    ):
        from teleclaude.core.agents import AgentName

        fake_parse.return_value = [AgentName.CLAUDE]
        telec._handle_history_search(["--agent", "claude", "config", "wizard"])

    assert captured["term"] == "config wizard"
    assert captured["limit"] == 20
    assert captured["computers"] is None


def test_handle_history_search_custom_limit(capsys: pytest.CaptureFixture[str]) -> None:
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    def fake_display(agents, search_term="", limit=20, computers=None):
        captured["limit"] = limit
        captured["computers"] = computers

    with (
        patch("teleclaude.history.search.parse_agents") as fake_parse,
        patch("teleclaude.history.search.display_combined_history", fake_display),
    ):
        from teleclaude.core.agents import AgentName

        fake_parse.return_value = [AgentName.CLAUDE]
        telec._handle_history_search(["--limit", "5", "foo"])

    assert captured["limit"] == 5
    assert captured["computers"] is None


def test_handle_history_show_no_session_id_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_history_show([])


def test_handle_history_show_calls_show_transcript() -> None:
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    def fake_show(agents, session_id, tail_chars=0, include_thinking=False, raw=False, computers=None):
        captured["session_id"] = session_id
        captured["tail"] = tail_chars
        captured["thinking"] = include_thinking
        captured["raw"] = raw
        captured["computers"] = computers

    with (
        patch("teleclaude.history.search.parse_agents") as fake_parse,
        patch("teleclaude.history.search.show_transcript", fake_show),
    ):
        from teleclaude.core.agents import AgentName

        fake_parse.return_value = [AgentName.CLAUDE]
        telec._handle_history_show(["abc123", "--thinking", "--tail", "2000"])

    assert captured["session_id"] == "abc123"
    assert captured["thinking"] is True
    assert captured["tail"] == 2000
    assert captured["raw"] is False
    assert captured["computers"] == []


# ---------------------------------------------------------------------------
# _handle_memories helpers
# ---------------------------------------------------------------------------


def test_handle_memories_no_args_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_memories([])
    out = capsys.readouterr().out
    assert "memories" in out


def test_handle_memories_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    telec._handle_memories(["--help"])
    out = capsys.readouterr().out
    assert "memories" in out


def test_handle_memories_unknown_subcommand_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories(["unknown"])


def test_handle_memories_search_no_query_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories_search([])


def test_handle_memories_search_calls_api(capsys: pytest.CaptureFixture[str]) -> None:
    fake_results = [
        {"id": 1, "type": "discovery", "project": "teleclaude", "title": "Test", "narrative": "Found something"}
    ]

    async def fake_memory_search(*args, **kwargs):
        return fake_results

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.memory_search = fake_memory_search

    with patch("teleclaude.cli.telec.TelecAPIClient", return_value=mock_client):
        telec._handle_memories_search(["session reason"])

    out = capsys.readouterr().out
    assert "session reason" in out
    assert "Test" in out


def test_handle_memories_search_invalid_type_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories_search(["query", "--type", "invalid-type"])


def test_handle_memories_search_daemon_down_exits(capsys: pytest.CaptureFixture[str]) -> None:
    async def fail_search(*args, **kwargs):
        raise APIError("Cannot connect to API server.", detail="Cannot connect to API server.")

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.memory_search = fail_search

    with patch("teleclaude.cli.telec.TelecAPIClient", return_value=mock_client):
        with pytest.raises(SystemExit):
            telec._handle_memories_search(["query"])

    out = capsys.readouterr().out
    assert "Error" in out


def test_handle_memories_save_no_text_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories_save([])


def test_handle_memories_save_calls_api(capsys: pytest.CaptureFixture[str]) -> None:
    fake_result = {"id": 42, "title": "My Finding", "project": "teleclaude"}

    async def fake_memory_save(*args, **kwargs):
        return fake_result

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.memory_save = fake_memory_save

    with patch("teleclaude.cli.telec.TelecAPIClient", return_value=mock_client):
        telec._handle_memories_save(["Important finding", "--title", "My Finding", "--type", "discovery", "--project", "teleclaude"])

    out = capsys.readouterr().out
    assert "42" in out
    assert "My Finding" in out


def test_handle_memories_delete_no_id_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories_delete([])


def test_handle_memories_delete_invalid_id_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories_delete(["not-a-number"])


def test_handle_memories_delete_calls_api(capsys: pytest.CaptureFixture[str]) -> None:
    async def fake_memory_delete(observation_id: int):
        return {"deleted": observation_id}

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.memory_delete = fake_memory_delete

    with patch("teleclaude.cli.telec.TelecAPIClient", return_value=mock_client):
        telec._handle_memories_delete(["123"])

    out = capsys.readouterr().out
    assert "123" in out


def test_handle_memories_timeline_no_anchor_exits() -> None:
    with pytest.raises(SystemExit):
        telec._handle_memories_timeline([])


def test_handle_memories_timeline_calls_api(capsys: pytest.CaptureFixture[str]) -> None:
    fake_results = [
        {"id": 40, "type": "discovery", "project": "teleclaude", "title": "Before", "narrative": "Earlier context"},
        {"id": 42, "type": "gotcha", "project": "teleclaude", "title": "Anchor", "narrative": "The anchor observation"},
        {"id": 44, "type": "pattern", "project": "teleclaude", "title": "After", "narrative": "Follow-up context"},
    ]

    async def fake_memory_timeline(*args, **kwargs):
        return fake_results

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.memory_timeline = fake_memory_timeline

    with patch("teleclaude.cli.telec.TelecAPIClient", return_value=mock_client):
        telec._handle_memories_timeline(["42", "--before", "1", "--after", "1"])

    out = capsys.readouterr().out
    assert "42" in out
    assert "Anchor" in out


# ---------------------------------------------------------------------------
# TelecAPIClient memory methods
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_client_memory_search_builds_params() -> None:
    from teleclaude.cli.api_client import TelecAPIClient

    client = TelecAPIClient()
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    async def fake_request(method, url, *, params=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        resp = MagicMock()
        resp.json.return_value = []
        return resp

    client._request = fake_request  # type: ignore[method-assign]

    await client.memory_search("test query", limit=5, obs_type="discovery", project="teleclaude")

    assert captured["url"] == "/api/memory/search"
    assert captured["params"]["query"] == "test query"
    assert captured["params"]["limit"] == "5"
    assert captured["params"]["type"] == "discovery"
    assert captured["params"]["project"] == "teleclaude"


@pytest.mark.anyio
async def test_api_client_memory_save_builds_body() -> None:
    from teleclaude.cli.api_client import TelecAPIClient

    client = TelecAPIClient()
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    async def fake_request(method, url, *, json_body=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = json_body
        resp = MagicMock()
        resp.json.return_value = {"id": 1, "title": "T", "project": "p"}
        return resp

    client._request = fake_request  # type: ignore[method-assign]

    await client.memory_save("text", title="T", obs_type="gotcha", project="p")

    assert captured["url"] == "/api/memory/save"
    assert captured["body"]["text"] == "text"
    assert captured["body"]["title"] == "T"
    assert captured["body"]["type"] == "gotcha"
    assert captured["body"]["project"] == "p"


@pytest.mark.anyio
async def test_api_client_memory_delete_correct_url() -> None:
    from teleclaude.cli.api_client import TelecAPIClient

    client = TelecAPIClient()
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    async def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        resp = MagicMock()
        resp.json.return_value = {"deleted": 99}
        return resp

    client._request = fake_request  # type: ignore[method-assign]

    await client.memory_delete(99)

    assert captured["url"] == "/api/memory/99"
    assert captured["method"] == "DELETE"


@pytest.mark.anyio
async def test_api_client_memory_timeline_builds_params() -> None:
    from teleclaude.cli.api_client import TelecAPIClient

    client = TelecAPIClient()
    captured: dict[str, Any] = {}  # guard: loose-dict - test capture dict

    async def fake_request(method, url, *, params=None, **kwargs):
        captured["params"] = params
        resp = MagicMock()
        resp.json.return_value = []
        return resp

    client._request = fake_request  # type: ignore[method-assign]

    await client.memory_timeline(42, before=2, after=4, project="myproject")

    assert captured["params"]["anchor"] == "42"
    assert captured["params"]["depth_before"] == "2"
    assert captured["params"]["depth_after"] == "4"
    assert captured["params"]["project"] == "myproject"


# ---------------------------------------------------------------------------
# CLI help output
# ---------------------------------------------------------------------------


def test_telec_help_shows_history_and_memories(capsys: pytest.CaptureFixture[str]) -> None:
    from teleclaude.cli.telec import _usage

    out = _usage()
    assert "history" in out
    assert "memories" in out
