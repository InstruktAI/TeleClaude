"""Functional bindings for the mirror reconciliation loop's self-healing re-derivation."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from teleclaude.constants import SlashCommand
from teleclaude.core.agents import AgentName
from teleclaude.mirrors import generator, store, worker
from teleclaude.mirrors.derivation import DERIVATION_VERSION, render_title
from teleclaude.utils.transcript_discovery import TranscriptCandidate, build_source_identity

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/session_mirrors/mirror-reconciliation-loop"

_FEATURE_SLUG = "my-feature"
_HUMAN_QUESTION = "Why is search slow?"
_SUMMARY_TEXT = "summary"


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


def _write_transcript(path: Path) -> None:
    entries = [
        {
            "timestamp": "2026-06-01T00:00:00Z",
            "message": {"role": "user", "content": _HUMAN_QUESTION},
        },
        {
            "timestamp": "2026-06-01T00:00:01Z",
            "message": {"role": "assistant", "content": "Indexing scans every mirror row."},
        },
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")


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


@pytest.mark.spec(_SPEC, "UC-MRL-8")
async def test_wedged_pass_does_not_stall_reconciliation_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = str(tmp_path / "wedged.db")
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript)
    source = build_source_identity(transcript, AgentName.CLAUDE)
    candidate = TranscriptCandidate(path=transcript, agent=AgentName.CLAUDE, mtime=1000.0)
    monkeypatch.setattr(worker, "_discover_transcripts", lambda *_a, **_k: [candidate])
    monkeypatch.setattr(worker, "RECONCILE_PASS_TIMEOUT_S", 0.05, raising=False)

    first_call_blocked = threading.Event()
    release_first_call = threading.Event()
    calls = 0

    async def _fake_summarizer(*_args: object, **_kwargs: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_call_blocked.set()
            await asyncio.to_thread(release_first_call.wait)
        return _SUMMARY_TEXT

    monkeypatch.setattr(generator, "_call_summarizer", _fake_summarizer)

    mirror_worker = worker.MirrorWorker(db=db, interval_s=0.01)
    run_task = asyncio.create_task(mirror_worker.run())
    try:
        await asyncio.wait_for(asyncio.to_thread(first_call_blocked.wait), timeout=1.0)

        async def _mirror_generated() -> store.MirrorRecord:
            while True:
                record = await asyncio.to_thread(store.get_mirror, source_identity=source, db=db)
                if record is not None:
                    return record
                await asyncio.sleep(0.01)

        record = await asyncio.wait_for(_mirror_generated(), timeout=1.0)
        assert record.summary == _SUMMARY_TEXT
    finally:
        release_first_call.set()
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
