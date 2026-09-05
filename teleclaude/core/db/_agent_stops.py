"""Persistence for the agent-stop output transaction."""

import json
from datetime import datetime

from sqlalchemy import text

from teleclaude.core.event_bus import event_bus
from teleclaude.core.session_output import StopOutputDisposition
from teleclaude.events.envelope import EventVisibility

from ..events import SessionUpdatedContext, TeleClaudeEvents
from ..models import SessionField

_PERSIST_AGENT_STOP_SUMMARY_SQL = (
    "UPDATE sessions SET"
    " last_output_raw = :raw_output,"
    " last_output_summary = :summary,"
    " last_output_at = :summary_at"
    " WHERE session_id = :session_id"
    " AND last_agent_stop_at = :stop_iso"
    " AND last_output_stop_at = :stop_iso"
)
_PERSIST_SUMMARY_SESSION_ID_PARAMETER = "session_id"
_PERSIST_SUMMARY_STOP_PARAMETER = "stop_iso"
_PERSIST_SUMMARY_RAW_OUTPUT_PARAMETER = "raw_output"
_PERSIST_SUMMARY_VALUE_PARAMETER = "summary"
_PERSIST_SUMMARY_AT_PARAMETER = "summary_at"


class DbAgentStopsMixin:
    """Persist agent-stop state and its output projection atomically."""

    async def stage_agent_stop(
        self,
        session_id: str,
        *,
        stop_at: datetime,
        raw_output: str | None,
        output_disposition: StopOutputDisposition,
        owed_lanes: list[str],
        known_ui_lanes: list[str],
        expected_stop_at: datetime | None = None,
    ) -> bool:
        """Persist one agent-stop transition with an explicit output disposition."""
        stop_iso = stop_at.isoformat()
        expected_stop_iso = expected_stop_at.isoformat() if expected_stop_at is not None else None
        expected_stop_clause = " AND last_agent_stop_at = :expected_stop_iso" if expected_stop_iso else ""
        updated_fields: dict[str, object] = {  # guard: loose-dict - session event delta
            "last_activity": stop_iso,
            "last_agent_stop_at": stop_iso,
        }

        if output_disposition is StopOutputDisposition.PRESERVE:
            statement = (
                "UPDATE sessions SET last_activity = :stop_iso, last_agent_stop_at = :stop_iso "
                "WHERE session_id = :session_id"
                f"{expected_stop_clause}"
            )
            parameters = {
                "stop_iso": stop_iso,
                "expected_stop_iso": expected_stop_iso,
                "session_id": session_id,
            }
        else:
            patch: dict[str, object] = {  # guard: loose-dict - JSON merge patch
                lane: {"final_output_due_at": stop_iso if lane in owed_lanes else None} for lane in known_ui_lanes
            }
            output_at = stop_iso if raw_output is not None else None
            statement = (
                "UPDATE sessions SET"
                " last_activity = :stop_iso,"
                " last_agent_stop_at = :stop_iso,"
                " last_output_raw = :raw_output,"
                " last_output_summary = NULL,"
                " last_output_at = :output_at,"
                " last_output_stop_at = :output_at,"
                " origin_metadata = '' || json_patch(COALESCE(origin_metadata, '{}'), json(:patch_json))"
                " WHERE session_id = :session_id"
                f"{expected_stop_clause}"
            )
            parameters = {
                "stop_iso": stop_iso,
                "raw_output": raw_output,
                "output_at": output_at,
                "patch_json": json.dumps(patch),
                "expected_stop_iso": expected_stop_iso,
                "session_id": session_id,
            }
            updated_fields.update(
                {
                    "last_output_raw": raw_output,
                    "last_output_summary": None,
                    "last_output_at": output_at,
                    "last_output_stop_at": output_at,
                }
            )

        async with self._session() as db_session:
            result = await db_session.exec(
                text(statement).bindparams(**parameters)
            )  # guard: raw-sql - atomic stop transition
            await db_session.commit()
        accepted = (result.rowcount or 0) == 1
        if not accepted:
            return False

        event_bus.emit(
            TeleClaudeEvents.SESSION_UPDATED,
            SessionUpdatedContext(
                session_id=session_id,
                updated_fields=updated_fields,
            ),
            visibility=EventVisibility.CLUSTER,
        )
        return True

    async def persist_agent_stop_summary(
        self,
        session_id: str,
        *,
        stop_at: datetime,
        raw_output: str,
        summary: str | None,
        summary_at: datetime,
    ) -> bool:
        """Persist a slow summary only while its output stop remains current."""
        stop_iso = stop_at.isoformat()
        summary_iso = summary_at.isoformat()
        updated_fields: dict[str, object] = {  # guard: loose-dict - session event delta
            SessionField.LAST_OUTPUT_RAW.value: raw_output,
            SessionField.LAST_OUTPUT_SUMMARY.value: summary,
            SessionField.LAST_OUTPUT_AT.value: summary_iso,
        }
        parameters = {
            _PERSIST_SUMMARY_SESSION_ID_PARAMETER: session_id,
            _PERSIST_SUMMARY_STOP_PARAMETER: stop_iso,
            _PERSIST_SUMMARY_RAW_OUTPUT_PARAMETER: raw_output,
            _PERSIST_SUMMARY_VALUE_PARAMETER: summary,
            _PERSIST_SUMMARY_AT_PARAMETER: summary_iso,
        }
        async with self._session() as db_session:
            result = await db_session.exec(
                text(_PERSIST_AGENT_STOP_SUMMARY_SQL).bindparams(**parameters)
            )  # guard: raw-sql - conditional output persistence must be atomic
            await db_session.commit()
        accepted = (result.rowcount or 0) == 1
        if not accepted:
            return False

        event_bus.emit(
            TeleClaudeEvents.SESSION_UPDATED,
            SessionUpdatedContext(
                session_id=session_id,
                updated_fields=updated_fields,
            ),
            visibility=EventVisibility.CLUSTER,
        )
        return True
