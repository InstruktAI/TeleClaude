"""Background reconciliation worker for mirror generation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agents import AgentName

from ..utils.transcript_discovery import (
    TranscriptCandidate,
    build_source_identity,
    extract_project,
    extract_session_id,
    in_session_root,
)
from ..utils.transcript_discovery import discover_transcripts as _discover_transcripts
from .generator import generate_mirror_sync
from .store import (
    MirrorTombstoneRecord,
    delete_mirror,
    delete_mirror_tombstone,
    get_mirror_state_by_transcript,
    get_mirror_tombstone,
    resolve_db_path,
    upsert_mirror_tombstone,
)

logger = get_logger(__name__)

RECONCILE_INTERVAL_S = 300

__all__ = ["MirrorWorker", "ReconcileResult", "TranscriptCandidate"]


@dataclass
class ReconcileResult:
    discovered: int
    processed: int
    failed: int
    skipped_unchanged: int
    duration_s: float


class MirrorWorker:
    """Idempotent reconciliation loop for stale or missing mirrors."""

    def __init__(self, db: object | None = None, interval_s: int = RECONCILE_INTERVAL_S) -> None:
        self.db_path = resolve_db_path(db)
        self.interval_s = interval_s

    def _wal_size_kb(self) -> int:
        wal_path = Path(f"{self.db_path}-wal")
        if not wal_path.exists():
            return 0
        return wal_path.stat().st_size // 1024

    @staticmethod
    def _parse_updated_at(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _candidate_file_state(candidate: TranscriptCandidate) -> tuple[int, str]:
        stat = candidate.path.stat()
        return stat.st_size, str(stat.st_mtime_ns)

    def _should_skip_tombstoned_transcript(self, source_identity: str, candidate: TranscriptCandidate) -> bool:
        tombstone = get_mirror_tombstone(source_identity, db=self.db_path)
        if tombstone is None:
            return False
        file_size, file_mtime = self._candidate_file_state(candidate)
        if tombstone.file_size == file_size and tombstone.file_mtime == file_mtime:
            return True
        delete_mirror_tombstone(source_identity, db=self.db_path)
        return False

    def _record_tombstone(self, source_identity: str, candidate: TranscriptCandidate) -> None:
        file_size, file_mtime = self._candidate_file_state(candidate)
        upsert_mirror_tombstone(
            MirrorTombstoneRecord(
                source_identity=source_identity,
                agent=candidate.agent.value,
                transcript_path=str(candidate.path),
                file_size=file_size,
                file_mtime=file_mtime,
                created_at=datetime.now(UTC).isoformat(),
            ),
            db=self.db_path,
        )

    def _log_reconcile_result(self, result: ReconcileResult, wal_before_kb: int, wal_after_kb: int) -> None:
        logger.info(
            "mirror.reconciliation.complete "
            f"discovered={result.discovered} "
            f"processed={result.processed} "
            f"failed={result.failed} "
            f"skipped_unchanged={result.skipped_unchanged} "
            f"duration_s={result.duration_s:.3f} "
            f"wal_before_kb={wal_before_kb} "
            f"wal_after_kb={wal_after_kb}"
        )

    def _reconcile_sync(self) -> ReconcileResult:
        """Reconcile all known transcripts once."""
        wal_before_kb = self._wal_size_kb()
        started_at = perf_counter()
        state = get_mirror_state_by_transcript(self.db_path)
        transcripts = _discover_transcripts()
        result = ReconcileResult(
            discovered=len(transcripts),
            processed=0,
            failed=0,
            skipped_unchanged=0,
            duration_s=0.0,
        )

        for candidate in transcripts:
            transcript_path = str(candidate.path)
            try:
                mtime_dt = datetime.fromtimestamp(candidate.mtime or candidate.path.stat().st_mtime, tz=UTC)
                existing = state.get(transcript_path)
                updated_at = existing[1] if existing else None
                parsed_updated = self._parse_updated_at(updated_at)
                if parsed_updated is not None and parsed_updated >= mtime_dt:
                    result.skipped_unchanged += 1
                    continue

                source_identity = build_source_identity(candidate.path, candidate.agent)
                if self._should_skip_tombstoned_transcript(source_identity, candidate):
                    result.skipped_unchanged += 1
                    continue

                session_id = extract_session_id(candidate.path, candidate.agent)
                computer = config.computer.name
                project = extract_project(candidate.path, candidate.agent)

                generated = generate_mirror_sync(
                    session_id=session_id,
                    source_identity=source_identity,
                    transcript_path=transcript_path,
                    agent_name=candidate.agent,
                    computer=computer,
                    project=project,
                    db=self.db_path,
                )
                if generated:
                    delete_mirror_tombstone(source_identity, db=self.db_path)
                else:
                    self._record_tombstone(source_identity, candidate)
                    delete_mirror(session_id=session_id, source_identity=source_identity, db=self.db_path)
                result.processed += 1
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result.failed += 1
                logger.error(
                    "Mirror reconciliation failed for transcript %s (%s): %s",
                    transcript_path,
                    candidate.agent.value,
                    exc,
                    exc_info=True,
                )

        result.duration_s = perf_counter() - started_at
        wal_after_kb = self._wal_size_kb()
        self._log_reconcile_result(result, wal_before_kb, wal_after_kb)
        return result

    def backfill_sync(self) -> ReconcileResult:
        """Remove stale mirror rows and repopulate canonical rows from transcripts."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT id, agent, source_identity, metadata FROM mirrors").fetchall()
                delete_ids: list[int] = []
                for row in rows:
                    source_identity = row["source_identity"]
                    if not source_identity:
                        delete_ids.append(int(row["id"]))
                        continue
                    try:
                        metadata = json.loads(row["metadata"] or "{}")
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(metadata, dict):
                        continue
                    transcript_path = metadata.get("transcript_path")
                    if not isinstance(transcript_path, str) or not transcript_path:
                        continue
                    agent_value = row["agent"]
                    try:
                        agent = AgentName(str(agent_value))
                    except ValueError:
                        continue
                    if not in_session_root(transcript_path, agent):
                        delete_ids.append(int(row["id"]))
                for row_id in delete_ids:
                    conn.execute("DELETE FROM mirrors WHERE id = ?", (row_id,))
                conn.commit()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise

        return self._reconcile_sync()

    async def run_once(self) -> ReconcileResult:
        """Reconcile all known transcripts once."""
        return await asyncio.to_thread(self._reconcile_sync)

    async def run(self) -> None:
        """Run reconciliation on startup and every interval until cancelled."""
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Mirror reconciliation cycle failed: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval_s)
