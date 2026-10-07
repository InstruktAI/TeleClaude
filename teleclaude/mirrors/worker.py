"""Background reconciliation worker for mirror generation."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db._sync import get_session_closed_at_sync
from teleclaude.paths import MAIN_DB_PATH, MIRRORS_DB_PATH  # stable constants — not monkeypatched

from ..utils.transcript_discovery import (
    TranscriptCandidate,
    build_source_identity,
    extract_project,
    extract_session_id,
    in_session_root,
)
from ..utils.transcript_discovery import discover_transcripts as _discover_transcripts
from ._reconciliation_state import MirrorTranscriptState, get_mirror_state_by_transcript, get_stale_mirrors
from .derivation import DERIVATION_VERSION
from .generator import MirrorGenerationOutcome, MirrorWriteTrigger, generate_mirror_sync
from .session_context import get_session_context
from .store import (
    MirrorTombstoneRecord,
    delete_mirror_tombstone,
    get_mirror_tombstones,
    mark_mirror_unreprojectable,
    open_attributed_session_ids,
    record_session_close,
    upsert_mirror_tombstone,
)

logger = get_logger(__name__)

RECONCILE_INTERVAL_S = 300
RECONCILE_PASS_TIMEOUT_S = 240
MIRROR_RECONCILIATION_ACCEPTED = "mirror.reconciliation.accepted"
MIRROR_RECONCILIATION_COMPLETE = "mirror.reconciliation.complete"
MIRROR_SESSION_ATTRIBUTION_CLOSED_EVENT = "mirror.session_attribution.closed_recorded"

__all__ = ["MirrorWorker", "ReconcileResult", "TranscriptCandidate"]


@dataclass
class ReconcileResult:
    """Outcome counters from a single reconciliation pass."""

    discovered: int
    regenerated: int
    shrink_accepted: int
    shrink_refused: int
    failed: int
    orphan_unreprojectable: int
    skipped_unchanged: int
    duration_s: float


class MirrorWorker:
    """Idempotent reconciliation loop for stale or missing mirrors."""

    def __init__(self, db: str | Path | None = None, interval_s: int = RECONCILE_INTERVAL_S) -> None:
        self.db_path = str(Path(db).expanduser()) if db is not None else str(MIRRORS_DB_PATH)
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

    def _is_unchanged_mirror(
        self,
        candidate: TranscriptCandidate,
        state: dict[str, MirrorTranscriptState],
    ) -> bool:
        mtime_dt = datetime.fromtimestamp(candidate.mtime or candidate.path.stat().st_mtime, tz=UTC)
        existing = state.get(str(candidate.path))
        parsed_updated = self._parse_updated_at(existing.updated_at if existing else None)
        version_current = existing is not None and existing.derivation_version >= DERIVATION_VERSION
        return parsed_updated is not None and parsed_updated >= mtime_dt and version_current

    def _should_skip_tombstoned_transcript(
        self,
        source_identity: str,
        candidate: TranscriptCandidate,
        tombstone: MirrorTombstoneRecord | None,
    ) -> bool:
        if tombstone is None:
            return False
        file_size, file_mtime = self._candidate_file_state(candidate)
        if tombstone.file_size == file_size and tombstone.file_mtime == file_mtime:
            return True
        delete_mirror_tombstone(source_identity, db=self.db_path)
        return False

    def _record_tombstone(self, source_identity: str, candidate: TranscriptCandidate) -> MirrorTombstoneRecord:
        file_size, file_mtime = self._candidate_file_state(candidate)
        record = MirrorTombstoneRecord(
            source_identity=source_identity,
            agent=candidate.agent.value,
            transcript_path=str(candidate.path),
            file_size=file_size,
            file_mtime=file_mtime,
            created_at=datetime.now(UTC).isoformat(),
        )
        upsert_mirror_tombstone(record, db=self.db_path)
        return record

    def _log_reconcile_result(
        self,
        result: ReconcileResult,
        *,
        reconcile_id: str,
        wal_before_kb: int,
        wal_after_kb: int,
    ) -> None:
        logger.info(
            MIRROR_RECONCILIATION_COMPLETE,
            reconcile_id=reconcile_id,
            derivation_version=DERIVATION_VERSION,
            discovered=result.discovered,
            regenerated=result.regenerated,
            shrink_accepted=result.shrink_accepted,
            shrink_refused=result.shrink_refused,
            failed=result.failed,
            orphan_unreprojectable=result.orphan_unreprojectable,
            skipped_unchanged=result.skipped_unchanged,
            duration_s=result.duration_s,
            wal_before_kb=wal_before_kb,
            wal_after_kb=wal_after_kb,
        )

    def _reconcile_sync(self) -> ReconcileResult:
        """Reconcile all known transcripts once."""
        wal_before_kb = self._wal_size_kb()
        started_at = perf_counter()
        reconcile_id = str(uuid4())
        logger.info(
            MIRROR_RECONCILIATION_ACCEPTED,
            reconcile_id=reconcile_id,
            derivation_version=DERIVATION_VERSION,
        )
        state = get_mirror_state_by_transcript(self.db_path)

        def known_unchanged(candidate: TranscriptCandidate) -> bool:
            try:
                return self._is_unchanged_mirror(candidate, state)
            except ValueError:
                # Invalid stored timestamps are handled by the per-candidate error lane.
                return False

        transcripts = _discover_transcripts(known_unchanged=known_unchanged)
        tombstones = get_mirror_tombstones(self.db_path)
        result = ReconcileResult(
            discovered=len(transcripts),
            regenerated=0,
            shrink_accepted=0,
            shrink_refused=0,
            failed=0,
            orphan_unreprojectable=0,
            skipped_unchanged=0,
            duration_s=0.0,
        )

        for candidate in transcripts:
            transcript_path = str(candidate.path)
            try:
                if self._is_unchanged_mirror(candidate, state):
                    result.skipped_unchanged += 1
                    continue

                source_identity = build_source_identity(candidate.path, candidate.agent)
                if self._should_skip_tombstoned_transcript(source_identity, candidate, tombstones.get(source_identity)):
                    result.skipped_unchanged += 1
                    continue
                tombstones.pop(source_identity, None)

                native_session_id = extract_session_id(candidate.path, candidate.agent)
                context = get_session_context(transcript_path=transcript_path)
                fallback_project_path = extract_project(candidate.path, candidate.agent) if context is None else None

                outcome = generate_mirror_sync(
                    native_session_id=native_session_id,
                    source_identity=source_identity,
                    transcript_path=transcript_path,
                    agent_name=candidate.agent,
                    db=self.db_path,
                    context=context,
                    trigger=MirrorWriteTrigger.RECONCILE,
                    reconcile_id=reconcile_id,
                    fallback_project_path=fallback_project_path,
                )
                if outcome in {MirrorGenerationOutcome.GENERATED, MirrorGenerationOutcome.SHRINK_ACCEPTED}:
                    delete_mirror_tombstone(source_identity, db=self.db_path)
                    result.regenerated += 1
                    if outcome is MirrorGenerationOutcome.SHRINK_ACCEPTED:
                        result.shrink_accepted += 1
                elif outcome is MirrorGenerationOutcome.SHRINK_REFUSED:
                    result.shrink_refused += 1
                else:
                    # Tombstone only. Generation declining is evidence about the source,
                    # never a verdict on the stored mirror — an existing row keeps its
                    # conversation text, which for most sessions is the only copy left.
                    tombstones[source_identity] = self._record_tombstone(source_identity, candidate)
            except Exception as exc:
                result.failed += 1
                logger.error(
                    "Mirror reconciliation failed for transcript %s (%s): %s",
                    transcript_path,
                    candidate.agent.value,
                    exc,
                    exc_info=True,
                )

        self._record_session_closes(reconcile_id)
        self._rederive_orphans(result)

        result.duration_s = perf_counter() - started_at
        wal_after_kb = self._wal_size_kb()
        self._log_reconcile_result(
            result,
            reconcile_id=reconcile_id,
            wal_before_kb=wal_before_kb,
            wal_after_kb=wal_after_kb,
        )
        return result

    def _record_session_closes(self, reconcile_id: str) -> None:
        """Record newly closed mirror sessions from the owning session store."""
        session_ids = open_attributed_session_ids(db=self.db_path)
        close_times = get_session_closed_at_sync(str(MAIN_DB_PATH), session_ids)
        for session_id, closed_at in close_times.items():
            if record_session_close(session_id, closed_at, db=self.db_path):
                logger.info(
                    MIRROR_SESSION_ATTRIBUTION_CLOSED_EVENT,
                    session_id=session_id,
                    closed_at=closed_at,
                    reconcile_id=reconcile_id,
                )

    def _rederive_orphans(self, result: ReconcileResult) -> None:
        """Mark stale mirrors that have no source transcript for truthful exclusion."""
        for orphan in get_stale_mirrors(DERIVATION_VERSION, db=self.db_path):
            if orphan.transcript_path is not None and Path(orphan.transcript_path).expanduser().exists():
                continue
            try:
                mark_mirror_unreprojectable(
                    orphan.source_identity,
                    marked_at=datetime.now(UTC).isoformat(),
                    db=self.db_path,
                )
                result.orphan_unreprojectable += 1
            except Exception as exc:
                result.failed += 1
                logger.error(
                    "Mirror orphan re-derivation failed for %s (%s): %s",
                    orphan.source_identity,
                    orphan.agent,
                    exc,
                    exc_info=True,
                )

    def backfill_sync(self) -> ReconcileResult:
        """Remove stale mirror rows and repopulate canonical rows from transcripts.

        Tombstones are cleared first: they cache "this transcript has no
        conversation" keyed by file size/mtime, so a parser/format fix (e.g. new
        agy transcript schema) cannot invalidate them on its own. A backfill is an
        explicit "re-evaluate everything", so stale negatives must be forgotten.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute("DELETE FROM mirror_tombstones")
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
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
                # ``to_thread`` work cannot be force-cancelled; this releases the loop while the stuck thread drains.
                await asyncio.wait_for(self.run_once(), timeout=RECONCILE_PASS_TIMEOUT_S)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                logger.error(
                    "Mirror reconciliation pass exceeded %.1fs budget; proceeding to next cycle",
                    RECONCILE_PASS_TIMEOUT_S,
                )
            except Exception as exc:
                logger.error("Mirror reconciliation cycle failed: %s", exc, exc_info=True)
            await asyncio.sleep(self.interval_s)
