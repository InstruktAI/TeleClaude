"""Functional bindings for the mirror reconciliation loop's self-healing re-derivation."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.constants import SlashCommand
from teleclaude.core.agents import AgentName
from teleclaude.mirrors import store, worker
from teleclaude.mirrors.derivation import DERIVATION_VERSION, render_title
from teleclaude.utils.transcript_discovery import TranscriptCandidate, build_source_identity

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/session_mirrors/mirror-reconciliation-loop"

_FEATURE_SLUG = "my-feature"
_HUMAN_QUESTION = "Why is search slow?"


def _seed(db: str, *, source: str, session: str, transcript_path: str, conversation: str, version: int) -> None:
    store.upsert_mirror(
        store.MirrorRecord(
            session_id=session,
            computer="box",
            agent="claude",
            project="proj",
            title="stale title",
            timestamp_start="2026-06-01T00:00:00Z",
            timestamp_end="2026-06-01T00:00:00Z",
            conversation_text=conversation,
            message_count=1,
            metadata={"transcript_path": transcript_path},
            created_at="2026-06-01T00:00:00Z",
            updated_at="2026-06-01T00:00:00Z",
            source_identity=source,
            is_agent_spawn=False,
            derivation_version=version,
        ),
        db=db,
    )


@pytest.mark.spec(_SPEC, "UC-MRL-2")
def test_stale_version_row_rederives_despite_fresh_mtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "recon.db")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}", encoding="utf-8")
    source = build_source_identity(transcript, AgentName.CLAUDE)

    # Stored updated_at is newer than the candidate mtime, so the mtime check alone would skip.
    _seed(db, source=source, session="sess", transcript_path=str(transcript), conversation="hi", version=0)
    candidate = TranscriptCandidate(path=transcript, agent=AgentName.CLAUDE, mtime=1000.0)
    monkeypatch.setattr(worker, "_discover_transcripts", lambda *_a, **_k: [candidate])

    generated_for: list[str] = []

    def _spy(**kwargs: object) -> bool:
        generated_for.append(str(kwargs["source_identity"]))
        store.update_mirror_derivation(
            str(kwargs["source_identity"]),
            title="rederived",
            command=None,
            slug=None,
            is_agent_spawn=False,
            derivation_version=DERIVATION_VERSION,
            db=db,
        )
        return True

    monkeypatch.setattr(worker, "generate_mirror_sync", _spy)

    mirror_worker = worker.MirrorWorker(db=db)
    mirror_worker._reconcile_sync()
    assert generated_for == [source]  # stale version forces re-derivation despite fresh mtime

    mirror_worker._reconcile_sync()
    assert generated_for == [source]  # version now current → skipped, not re-derived again


@pytest.mark.spec(_SPEC, "UC-MRL-5")
def test_orphan_rows_rederive_in_place_and_are_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "orphan.db")
    monkeypatch.setattr(worker, "_discover_transcripts", lambda *_a, **_k: [])

    missing = str(tmp_path / "gone.jsonl")
    worker_convo = (
        f"[2026-06-01T00:00:00Z] User: /next-finalize {_FEATURE_SLUG}\n\n[2026-06-01T00:00:01Z] Assistant: ok"
    )
    _seed(db, source="orphan-worker", session="ow", transcript_path=missing, conversation=worker_convo, version=0)
    human_convo = f"[2026-06-01T00:00:00Z] User: {_HUMAN_QUESTION}\n\n[2026-06-01T00:00:01Z] Assistant: indexing"
    _seed(db, source="orphan-human", session="oh", transcript_path=missing + "2", conversation=human_convo, version=0)

    worker.MirrorWorker(db=db)._reconcile_sync()

    spawn = store.get_mirror("ow", db=db)
    assert spawn is not None
    assert spawn.is_agent_spawn is True
    assert spawn.command == SlashCommand.NEXT_FINALIZE.value
    assert spawn.title == render_title(SlashCommand.NEXT_FINALIZE.value, _FEATURE_SLUG)
    assert spawn.derivation_version == DERIVATION_VERSION

    human = store.get_mirror("oh", db=db)
    assert human is not None
    assert human.is_agent_spawn is False
    assert human.title == _HUMAN_QUESTION
    assert human.derivation_version == DERIVATION_VERSION

    # Second pass: versions are current, so nothing is re-derived.
    worker.MirrorWorker(db=db)._reconcile_sync()
    again = store.get_mirror("ow", db=db)
    assert again is not None
    assert again.title == render_title(SlashCommand.NEXT_FINALIZE.value, _FEATURE_SLUG)
