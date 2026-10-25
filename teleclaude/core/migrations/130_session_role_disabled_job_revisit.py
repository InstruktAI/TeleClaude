"""Map the job-runner rows migration 119 left unmapped because no configured job carried their recorded job name.

The 119 ledger is the only record of the retired ``system_role``. Only its entries with that reason are revisited,
and a session is changed only while it still carries the ``unmapped`` role and the recorded job and command, so a row
an operator has since resolved is left alone. Each entry is rebuilt as the row 119 read and mapped by 119's own
mapper, which resolves a job name through every declared job, disabled ones included; a job no declaration carries
stays unmapped. Without a 119 ledger nothing changes. The report is published before any row changes, and the rows and
their persisted launch intents change in one transaction. See
``local/projects/teleclaude/spec/feature/agent_runtime/session-role-migration``.
"""

import json
import os
from enum import StrEnum
from importlib import import_module
from typing import Any, Final

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.paths import STATE_DIR

logger = get_logger(__name__)

#: Migration module names start with digits, so the module is loaded by name rather than by an import statement.
_ROLE_MIGRATION: Final = import_module("teleclaude.core.migrations.119_session_role")

_MIGRATION_NAME: Final = "130_session_role_disabled_job_revisit"
_STATE_SUBDIRECTORY: Final = "migrations"
_SOURCE_LEDGER_PATH: Final = STATE_DIR / _STATE_SUBDIRECTORY / "119_session_role.json"
_REPORT_PATH: Final = STATE_DIR / _STATE_SUBDIRECTORY / f"{_MIGRATION_NAME}.json"
_ENCODING: Final = "utf-8"
_REPORT_WRITE_MODE: Final = "w"
_REPORT_TEMPORARY_SUFFIX: Final = ".tmp"
_SELECT_SESSION_SQL: Final = "SELECT role, job, command, project_path FROM sessions WHERE session_id = ?"
_UPDATE_SESSION_SQL: Final = "UPDATE sessions SET role = ?, job = ?, command = ? WHERE session_id = ?"
_UPDATE_HANDOVER_SQL: Final = "UPDATE session_startup_handovers SET launch_intent_json = ? WHERE session_id = ?"
_BEGIN_SQL: Final = "BEGIN"
_NO_LEDGER_EVENT: Final = "session_role_revisit_no_ledger"
_COMPLETE_EVENT: Final = "session_role_revisit_complete"
_NOT_READY_EVENT: Final = "session_role_revisit_not_ready"

LedgerEntry = dict[str, str | None]


class ReportKey(StrEnum):
    """The keys of the report an operator reads."""

    REVISITED = "revisited"


def _refused_entries() -> list[LedgerEntry]:
    """The 119 ledger's unmapped entries refused because no configured job carried the recorded job name."""
    ledger = json.loads(_SOURCE_LEDGER_PATH.read_text(encoding=_ENCODING))
    refusal = _ROLE_MIGRATION.MappingReason.JOB_NAMES_NO_DECLARATION.value
    return [
        entry
        for entry in ledger[_ROLE_MIGRATION.LedgerKey.UNMAPPED]
        if entry[_ROLE_MIGRATION.LedgerKey.REASON] == refusal
    ]


async def _unchanged_since_119(db: aiosqlite.Connection, entry: LedgerEntry) -> tuple[bool, str | None]:
    """Whether the session still carries what 119 persisted for the entry, and the project it now records."""
    async with db.execute(_SELECT_SESSION_SQL, (entry[_ROLE_MIGRATION.LedgerKey.SESSION_ID],)) as cursor:
        current = await cursor.fetchone()
    if current is None:
        return False, None
    role, job, command, project_path = current
    unchanged = (
        role == _ROLE_MIGRATION.UNMAPPED_ROLE
        and job == entry[_ROLE_MIGRATION.LedgerKey.JOB]
        and command == entry[_ROLE_MIGRATION.LedgerKey.COMMAND]
    )
    return unchanged, project_path


async def _revisits(db: aiosqlite.Connection, entries: list[LedgerEntry]) -> list[tuple[Any, Any]]:
    """Each entry whose session is unchanged since 119, rebuilt as 119 read it and mapped by 119's mapper."""
    declarations = _ROLE_MIGRATION._Declarations()
    revisits: list[tuple[Any, Any]] = []
    for entry in entries:
        unchanged, project_path = await _unchanged_since_119(db, entry)
        if not unchanged:
            continue
        row = _ROLE_MIGRATION.SessionRow(
            entry[_ROLE_MIGRATION.LedgerKey.SESSION_ID],
            entry[_ROLE_MIGRATION.LedgerKey.SYSTEM_ROLE],
            entry[_ROLE_MIGRATION.LedgerKey.JOB],
            entry[_ROLE_MIGRATION.LedgerKey.COMMAND],
            project_path,
            entry[_ROLE_MIGRATION.LedgerKey.WORKING_SLUG],
        )
        revisits.append((row, _ROLE_MIGRATION._map_row(row, declarations)))
    return revisits


def _report_entry(row: Any, mapped: Any) -> dict[str, str | dict[str, str | None] | None]:
    """The recorded values, what the row maps to now and the declaration read."""
    keys = _ROLE_MIGRATION.LedgerKey
    declaration = mapped.declaration
    return {
        **_ROLE_MIGRATION._ledger_entry(row, mapped),
        keys.RESULT_ROLE: mapped.role,
        keys.RESULT_JOB: mapped.job,
        keys.RESULT_COMMAND: mapped.command,
        keys.DECLARATION: declaration.to_dict() if declaration is not None else None,
    }


def _publish_report(report_json: str) -> None:
    """Make the report durable where an operator reads it: write beside it, flush, fsync, rename into place.

    A failure raises here, before any row has changed.
    """
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _REPORT_PATH.with_name(_REPORT_PATH.name + _REPORT_TEMPORARY_SUFFIX)
    with temporary.open(_REPORT_WRITE_MODE, encoding=_ENCODING) as handle:
        handle.write(report_json)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(_REPORT_PATH)


async def up(db: aiosqlite.Connection) -> None:
    """Map the rows 119 refused for an undeclared job again, publish the report, then change the rows.

    The order follows 119: (1) every ledger entry still matching its row is rebuilt and mapped without a write — a
    declaration source the mapping needs and cannot read raises ``MigrationNotReady`` here, with every row as
    recorded and the migration unrecorded; (2) the report is made durable; (3) the rows that now map, and the
    launch intents persisted for them, change in one transaction. A row that still maps to nothing is not written.
    Without a 119 ledger there is no record of the retired system role, so nothing changes.
    """
    if not _SOURCE_LEDGER_PATH.exists():
        logger.info(_NO_LEDGER_EVENT, migration=_MIGRATION_NAME, ledger=str(_SOURCE_LEDGER_PATH))
        return

    try:
        revisits = await _revisits(db, _refused_entries())
    except _ROLE_MIGRATION.MigrationNotReady as exc:
        logger.error(
            _NOT_READY_EVENT,
            migration=_MIGRATION_NAME,
            source=exc.source.value,
            location=str(exc.location),
            procedure_id=exc.procedure_id,
            reason=exc.reason,
        )
        raise

    remapped = [(row, mapped) for row, mapped in revisits if mapped.reason is None]
    handovers = await _ROLE_MIGRATION._planned_handovers(db, {row.session_id: mapped.role for row, mapped in remapped})
    report = {ReportKey.REVISITED: [_report_entry(row, mapped) for row, mapped in revisits]}
    _publish_report(json.dumps(report, indent=2, sort_keys=True))

    await db.execute(_BEGIN_SQL)
    try:
        for row, mapped in remapped:
            await db.execute(
                _UPDATE_SESSION_SQL,
                (mapped.role, mapped.job, mapped.command, row.session_id),
            )
        for session_id, intent_json in handovers:
            await db.execute(_UPDATE_HANDOVER_SQL, (intent_json, session_id))
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    logger.info(
        _COMPLETE_EVENT,
        migration=_MIGRATION_NAME,
        revisited_count=len(revisits),
        remapped_count=len(remapped),
        unmapped_count=len(revisits) - len(remapped),
        report=str(_REPORT_PATH),
    )
