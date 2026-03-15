"""Characterization tests for teleclaude.helpers.agent_cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teleclaude.helpers import agent_cli
from teleclaude.helpers.agent_types import AgentName, ThinkingMode

pytestmark = pytest.mark.unit


class TestExtractJsonObject:
    def test_prefers_json_fence_when_present(self) -> None:
        text = 'noise\n```json\n{"answer": 1}\n```\ntrailing'

        assert agent_cli._extract_json_object(text) == '{"answer": 1}'

    def test_ignores_braces_inside_strings(self) -> None:
        text = 'prefix {"value":"{ not a brace count }","nested":{"ok":true}} suffix'

        assert agent_cli._extract_json_object(text) == '{"value":"{ not a brace count }","nested":{"ok":true}}'


class TestLoadSchema:
    def test_reads_schema_file_after_stripping_markdown_fence(self, tmp_path: Path) -> None:
        schema_path = tmp_path / "schema.json"
        schema_path.write_text('```json\n{"type":"object"}\n```', encoding="utf-8")

        assert agent_cli._load_schema(None, str(schema_path)) == {"type": "object"}

    def test_requires_schema_source(self) -> None:
        with pytest.raises(ValueError, match="schema is required"):
            agent_cli._load_schema(None, None)


class TestCliEnv:
    def test_strips_api_key_and_claude_code_prefixed_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "secret")
        monkeypatch.setenv("CLAUDE_CODE_TOKEN", "secret")
        monkeypatch.setenv("SAFE_VALUE", "kept")

        env = agent_cli._cli_env()

        assert "OPENAI_API_KEY" not in env
        assert "CLAUDE_CODE_TOKEN" not in env
        assert env["SAFE_VALUE"] == "kept"


class TestRunOnce:
    def test_extracts_stringified_result_field_for_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(agent_cli, "_pick_agent", lambda preferred: AgentName.CLAUDE)
        monkeypatch.setattr(
            agent_cli,
            "_run_agent",
            lambda *args, **kwargs: json.dumps({"result": '{"answer": "ok"}'}),
        )

        payload = agent_cli.run_once(
            agent="claude",
            thinking_mode=ThinkingMode.FAST.value,
            system="system",
            prompt="prompt",
            schema={"type": "object"},
        )

        assert payload["status"] == "ok"
        assert payload["agent"] == "claude"
        assert payload["result"] == {"answer": "ok"}

    def test_prefers_structured_output_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(agent_cli, "_pick_agent", lambda preferred: AgentName.CODEX)
        monkeypatch.setattr(
            agent_cli,
            "_run_agent",
            lambda *args, **kwargs: json.dumps({"structured_output": {"answer": 2}}),
        )

        payload = agent_cli.run_once(
            agent="codex",
            thinking_mode=ThinkingMode.FAST.value,
            system="system",
            prompt="prompt",
            schema={"type": "object"},
        )

        assert payload["agent"] == "codex"
        assert payload["result"] == {"answer": 2}
