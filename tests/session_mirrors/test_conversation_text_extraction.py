"""Functional bindings for mirror conversation-text extraction and derived projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.constants import SlashCommand
from teleclaude.core.agents import AgentName
from teleclaude.mirrors import generator, store
from teleclaude.mirrors.derivation import render_title
from teleclaude.utils.transcript import StructuredMessage

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/session_mirrors/conversation-text-extraction"

_BUILD_SLUG = "clean-mirror-search-index"
_REVIEW_SLUG = "my-slug"
_HUMAN_QUESTION = "How do I order results by recency?"
_GEMINI_QUESTION = "What changed in the schema?"
_TS_START = "2026-06-01T00:00:00Z"
_TS_END = "2026-06-01T00:01:00Z"

_CODEX_LOADER = (
    f"Read /home/x/.teleclaude/commands/next-review-plan.md and follow it exactly "
    f"as the active instruction set for this session.\n\n"
    f"Treat the following as provided inputs to that instruction set:\n{_REVIEW_SLUG}"
)


def _msg(role: str, text: str, *, ts: str = _TS_START) -> StructuredMessage:
    return StructuredMessage(role=role, type="text", text=text, timestamp=ts)


def _stub_messages(monkeypatch: pytest.MonkeyPatch, messages: list[StructuredMessage]) -> None:
    monkeypatch.setattr(generator, "extract_structured_messages", lambda *_a, **_k: list(messages))
    monkeypatch.setattr(generator, "_generate_session_summary", lambda *_a, **_k: None)


def _generate(
    db: Path, agent: AgentName, messages: list[StructuredMessage], monkeypatch: pytest.MonkeyPatch, *, source: str
) -> store.MirrorRecord:
    _stub_messages(monkeypatch, messages)
    generator.generate_mirror_sync(
        session_id=source,
        source_identity=source,
        transcript_path="/does/not/matter",
        agent_name=agent,
        computer="box",
        project="proj",
        db=str(db),
    )
    record = store.get_mirror(source_identity=source, db=str(db))
    assert record is not None
    return record


@pytest.mark.spec(_SPEC, "UC-CTE-4")
def test_launch_command_detection_and_spawn_classification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        (
            AgentName.CLAUDE,
            [_msg("user", f"/next-build {_BUILD_SLUG}\n\nADDITIONAL CONTEXT: go")],
            True,
            SlashCommand.NEXT_BUILD.value,
            _BUILD_SLUG,
        ),
        (AgentName.CODEX, [_msg("user", _CODEX_LOADER)], True, SlashCommand.NEXT_REVIEW_PLAN.value, _REVIEW_SLUG),
        (
            AgentName.GEMINI,
            [_msg("user", f"/next-finalize {_BUILD_SLUG}")],
            True,
            SlashCommand.NEXT_FINALIZE.value,
            _BUILD_SLUG,
        ),
        (AgentName.CLAUDE, [_msg("user", "just a normal question about ordering")], False, None, None),
    ]
    for index, (agent, messages, is_spawn, command, slug) in enumerate(cases):
        record = _generate(tmp_path / f"m{index}.db", agent, messages, monkeypatch, source=f"src{index}")
        assert record.is_agent_spawn is is_spawn
        assert record.command == command
        assert record.slug == slug


@pytest.mark.spec(_SPEC, "UC-CTE-5")
def test_title_derivation_for_spawn_and_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _generate(
        tmp_path / "spawn.db", AgentName.CLAUDE, [_msg("user", f"/next-build {_BUILD_SLUG}")], monkeypatch, source="sp"
    )
    assert spawn.title == render_title(SlashCommand.NEXT_BUILD.value, _BUILD_SLUG)

    human = _generate(
        tmp_path / "human.db",
        AgentName.CLAUDE,
        [_msg("user", f"{_HUMAN_QUESTION}\nsecond line that is dropped")],
        monkeypatch,
        source="hu",
    )
    assert human.title == _HUMAN_QUESTION


@pytest.mark.spec(_SPEC, "UC-CTE-2")
def test_strip_injected_machine_context_from_user_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    polluted = (
        f"# AGENTS.md instructions for /repo\n\n<INSTRUCTIONS>\nlots of policy\n</INSTRUCTIONS>\n\n"
        f"<system-reminder>noise</system-reminder>\n<hook_context>mem</hook_context>\n{_HUMAN_QUESTION}"
    )
    cleaned = _generate(tmp_path / "clean.db", AgentName.CODEX, [_msg("user", polluted)], monkeypatch, source="cl")
    # A clean title is only reachable when every injected block was stripped before derivation.
    assert cleaned.title == _HUMAN_QUESTION

    serialized = f"[{{'text': '<hook_context># Memory</hook_context>{_GEMINI_QUESTION}'}}]"
    recovered = _generate(tmp_path / "ser.db", AgentName.GEMINI, [_msg("user", serialized)], monkeypatch, source="se")
    assert recovered.title == _GEMINI_QUESTION


@pytest.mark.spec(_SPEC, "UC-CTE-8")
def test_successful_extraction_persists_projection_and_preserves_created_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "proj.db"
    messages = [
        _msg("user", f"/next-build {_BUILD_SLUG}", ts=_TS_START),
        _msg("assistant", "working", ts=_TS_END),
    ]
    record = _generate(db, AgentName.CLAUDE, messages, monkeypatch, source="pj")
    assert record.timestamp_start == _TS_START
    assert record.timestamp_end == _TS_END
    assert record.message_count == 2
    assert record.is_agent_spawn is True
    assert record.command == SlashCommand.NEXT_BUILD.value
    assert record.slug == _BUILD_SLUG
    created_at = record.created_at

    # Re-running generation upserts and preserves the original created_at.
    updated = _generate(db, AgentName.CLAUDE, messages, monkeypatch, source="pj")
    assert updated.created_at == created_at
