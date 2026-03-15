from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.mirrors import processors as processors_module
from teleclaude.mirrors.store import SessionMirrorContext

pytestmark = pytest.mark.unit


class TestProcessorRegistry:
    def test_register_processor_adds_each_processor_only_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def processor(event: processors_module.MirrorEvent) -> None:
            return None

        monkeypatch.setattr(processors_module, "_processors", [])

        processors_module.register_processor(processor)
        processors_module.register_processor(processor)

        assert processors_module.get_processors() == [processor]


class TestProcessMirrorEvent:
    async def test_process_mirror_event_generates_mirror_with_fallback_computer_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        transcript_path = tmp_path / "session-1.jsonl"
        transcript_path.write_text("transcript", encoding="utf-8")
        expected_transcript_path = str(transcript_path)
        generated_calls: list[tuple[str, str, str, str, str, str]] = []

        monkeypatch.setattr(processors_module, "resolve_db_path", lambda: "mirrors.sqlite")
        monkeypatch.setattr(
            processors_module,
            "get_session_context",
            lambda session_id=None, transcript_path=None, db=None: SessionMirrorContext(
                session_id="session-1",
                computer="",
                agent="claude",
                project="alpha",
                transcript_path=expected_transcript_path,
            ),
        )
        monkeypatch.setattr(processors_module, "in_session_root", lambda path, agent: True)
        monkeypatch.setattr(processors_module, "config", SimpleNamespace(computer=SimpleNamespace(name="fallback-box")))

        async def fake_generate_mirror(
            session_id: str,
            source_identity: str,
            transcript_path: str,
            agent_name: object,
            computer: str,
            project: str,
            db: object | None,
        ) -> None:
            generated_calls.append((session_id, source_identity, transcript_path, agent_name.value, computer, project))

        monkeypatch.setattr(processors_module, "generate_mirror", fake_generate_mirror)

        await processors_module.process_mirror_event(
            processors_module.MirrorEvent(session_id="session-1", transcript_path=None)
        )

        assert generated_calls == [
            (
                "session-1",
                f"claude:{transcript_path.as_posix()}",
                expected_transcript_path,
                "claude",
                "fallback-box",
                "alpha",
            )
        ]

    async def test_process_mirror_event_skips_unknown_agent_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        warnings: list[str] = []

        monkeypatch.setattr(processors_module, "resolve_db_path", lambda: "mirrors.sqlite")
        monkeypatch.setattr(
            processors_module,
            "get_session_context",
            lambda session_id=None, transcript_path=None, db=None: SessionMirrorContext(
                session_id="session-1",
                computer="mac",
                agent="unknown",
                project="alpha",
                transcript_path="/tmp/transcript.jsonl",
            ),
        )
        monkeypatch.setattr(
            processors_module.logger, "warning", lambda message, agent, session_id: warnings.append(str(agent))
        )

        await processors_module.process_mirror_event(
            processors_module.MirrorEvent(session_id="session-1", transcript_path="/tmp/transcript.jsonl")
        )

        assert warnings == ["unknown"]
