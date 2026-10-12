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
    in_session_root,
)
from ..utils.transcript_discovery import discover_transcripts as _discover_transcripts
from ._reconciliation_state import MirrorTranscriptState, get_mirror_state_by_transcript, get_stale_mirrors
from .archive import ArchiveAdopter, adopt_retained_history, adopt_unclaimed_transcript
from .closure import CoverageReporter, coverage_is_news
from .derivation import DERIVATION_VERSION
from .generator import MirrorCoverage, MirrorWriteTrigger, SourceReadOutcome, refresh_session_mirror_sync
from .session_context import get_session_context
from .store import (
    MirrorTombstoneRecord,
    delete_conversation_mirror,
    delete_mirror_tombstone,
    get_mirror_tombstones,
    mark_mirror_unreprojectable,
    open_attributed_session_ids,
    record_session_close,
    unready_session_ids,
    upsert_mirror_tombstone,
)

logger = get_logger(__name__)

RECONCILE_INTERVAL_S = 300
RECONCILE_PASS_TIMEOUT_S = 240
MIRROR_RECONCILIATION_ACCEPTED = "mirror.reconciliation.accepted"
MIRROR_RECONCILIATION_COMPLETE = "mirror.reconciliation.complete"
MIRROR_SESSION_ATTRIBUTION_CLOSED_EVENT = "mirror.session_attribution.closed_recorded"
MIRROR_SESSION_RECONCILE_FAILED = "mirror.session_reconcile.failed"
MIRROR_COVERAGE_REPORT_FAILED = "mirror.coverage_report.failed"
MIRROR_UNREADY_REFRESH_FAILED = "mirror.unready_refresh.failed"
UNREADY_REFRESH_BATCH = 50

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

    def __init__(
        self,
        db: str | Path | None = None,
        interval_s: int = RECONCILE_INTERVAL_S,
        archive_adopter: ArchiveAdopter | None = None,
        coverage_reporter: CoverageReporter | None = None,
    ) -> None:
        self.db_path = str(Path(db).expanduser()) if db is not None else str(MIRRORS_DB_PATH)
        self.interval_s = interval_s
        self._archive_adopter = archive_adopter
        self._coverage_reporter = coverage_reporter
        self._history_adopted = False

    def _wal_size_kb(self) -> int:
        wal_path = Path(f"{self.db_path}-wal")
        if not wal_path.exists():
            return 0
        return wal_path.stat().st_size // 1024

    @staticmethod
    def _candidate_file_state(candidate: TranscriptCandidate) -> tuple[int, str]:
        stat = candidate.path.stat()
        return stat.st_size, str(stat.st_mtime_ns)

    def _is_unchanged_source(
        self,
        candidate: TranscriptCandidate,
        state: dict[str, MirrorTranscriptState],
    ) -> bool:
        existing = state.get(str(candidate.path))
        if existing is None or existing.derivation_version < DERIVATION_VERSION:
            return False
        return (existing.file_size, existing.file_mtime_ns) == self._candidate_file_state(candidate)

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
        if self._archive_adopter is not None and not self._history_adopted:
            adopt_retained_history(self._archive_adopter, self.db_path)
            self._history_adopted = True
        state = get_mirror_state_by_transcript(self.db_path)

        def known_unchanged(candidate: TranscriptCandidate) -> bool:
            try:
                return self._is_unchanged_source(candidate, state)
            except OSError:
                # An unreadable file is handled by the per-candidate error lane.
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

        by_session: dict[str, list[tuple[TranscriptCandidate, str]]] = {}
        for candidate in transcripts:
            transcript_path = str(candidate.path)
            try:
                if self._is_unchanged_source(candidate, state):
                    result.skipped_unchanged += 1
                    continue
                source_identity = build_source_identity(candidate.path, candidate.agent)
                if self._should_skip_tombstoned_transcript(source_identity, candidate, tombstones.get(source_identity)):
                    result.skipped_unchanged += 1
                    continue
                tombstones.pop(source_identity, None)
                session_id = self._owning_session(candidate, transcript_path)
                if session_id is None:
                    result.skipped_unchanged += 1
                    continue
                by_session.setdefault(session_id, []).append((candidate, source_identity))
            except Exception as exc:
                result.failed += 1
                logger.error(
                    "Mirror reconciliation failed for transcript %s (%s): %s",
                    transcript_path,
                    candidate.agent.value,
                    exc,
                    exc_info=True,
                )

        for session_id, members in by_session.items():
            self._refresh_session(session_id, members, result, reconcile_id)
        self._refresh_unready(set(by_session), reconcile_id)

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

    def _owning_session(self, candidate: TranscriptCandidate, transcript_path: str) -> str | None:
        """The TeleClaude session whose lineage holds the transcript; history no session claims is archived first."""
        context = get_session_context(transcript_path=transcript_path)
        if context is not None:
            return context.session_id
        if self._archive_adopter is None:
            logger.debug("Mirror reconciliation skipped unclaimed transcript", transcript_path=transcript_path)
            return None
        return adopt_unclaimed_transcript(candidate.path, candidate.agent, self._archive_adopter)

    def _refresh_session(
        self,
        session_id: str,
        members: list[tuple[TranscriptCandidate, str]],
        result: ReconcileResult,
        reconcile_id: str,
    ) -> None:
        """Refresh one session's conversation once and account for every changed source it held."""
        try:
            coverage = refresh_session_mirror_sync(
                session_id, db=self.db_path, trigger=MirrorWriteTrigger.RECONCILE, reconcile_id=reconcile_id
            )
        except Exception as exc:
            result.failed += len(members)
            logger.error(MIRROR_SESSION_RECONCILE_FAILED, session_id=session_id, error=str(exc), exc_info=True)
            return
        if coverage is None:
            result.failed += len(members)
            return
        self._report_coverage(coverage)
        for candidate, source_identity in members:
            outcome = coverage.source_outcomes.get(source_identity)
            if outcome in {SourceReadOutcome.READ, SourceReadOutcome.SHRINK_ACCEPTED}:
                delete_mirror_tombstone(source_identity, db=self.db_path)
                result.regenerated += 1
                if outcome is SourceReadOutcome.SHRINK_ACCEPTED:
                    result.shrink_accepted += 1
            elif outcome is SourceReadOutcome.SHRINK_REFUSED:
                result.shrink_refused += 1
            elif outcome is SourceReadOutcome.NO_CONVERSATION:
                # Tombstone only. Generation declining is evidence about the source, never a verdict on the
                # stored mirror — an existing row keeps its conversation text, which for most sessions is the
                # only copy left.
                self._record_tombstone(source_identity, candidate)
            elif outcome is SourceReadOutcome.FAILED:
                result.failed += 1
            else:
                result.skipped_unchanged += 1

    def _refresh_unready(self, refreshed: set[str], reconcile_id: str) -> None:
        """Revisit conversations that are not ready though no source changed, so a missed report is made again."""
        for session_id in unready_session_ids(UNREADY_REFRESH_BATCH, db=self.db_path):
            if session_id in refreshed:
                continue
            try:
                coverage = refresh_session_mirror_sync(
                    session_id, db=self.db_path, trigger=MirrorWriteTrigger.RECONCILE, reconcile_id=reconcile_id
                )
            except Exception:
                logger.error(
                    MIRROR_UNREADY_REFRESH_FAILED, session_id=session_id, reconcile_id=reconcile_id, exc_info=True
                )
                continue
            if coverage is not None:
                self._report_coverage(coverage)

    def _report_coverage(self, coverage: MirrorCoverage) -> None:
        """Report coverage that is news; a failed report is logged, and the mirror stays unready until one succeeds."""
        if self._coverage_reporter is None or not coverage_is_news(coverage, MirrorWriteTrigger.RECONCILE):
            return
        try:
            self._coverage_reporter(coverage)
        except Exception as exc:
            logger.error(MIRROR_COVERAGE_REPORT_FAILED, session_id=coverage.session_id, error=str(exc), exc_info=True)

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
        delete_ids: list[int] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute("DELETE FROM mirror_tombstones")
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
                rows = conn.execute("SELECT id, agent, source_identity, metadata FROM mirrors").fetchall()
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
                conn.commit()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
        for row_id in delete_ids:
            delete_conversation_mirror(row_id, db=self.db_path)

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
