"""Enrichment cartridge — appends platform context to events with recognized entity URIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

logger = get_logger(__name__)


class EnrichmentCartridge:
    name = "enrichment"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        if event.entity is None:
            return event

        enrichment = await self._enrich(event.entity, context.db)
        if enrichment is None:
            return event

        updated_payload = dict(event.payload)
        updated_payload["_enrichment"] = enrichment
        return event.model_copy(update={"payload": updated_payload})

    async def _enrich(self, entity_uri: str, db: EventDB) -> dict[str, Any] | None:
        if not entity_uri.startswith("telec://"):
            return None

        remainder = entity_uri[len("telec://") :]
        parts = remainder.split("/", 1)
        if len(parts) != 2:
            return None

        entity_type, entity_id = parts[0], parts[1]

        if entity_type == "todo":
            return await self._enrich_todo(entity_id, entity_uri, db)
        if entity_type == "worker":
            return await self._enrich_worker(entity_id, entity_uri, db)

        return None

    async def _enrich_todo(self, entity_id: str, entity_uri: str, db: EventDB) -> dict[str, Any] | None:
        failure_count = await db.count_events_by_entity(
            entity_uri, "domain.software-development.build.completed", payload_filter={"success": False}
        )
        dor_payload = await db.get_latest_event_payload(entity_uri, "dor_assessed")
        phase_payload = await db.get_latest_event_payload(entity_uri, "todo_activated")

        if failure_count == 0 and dor_payload is None and phase_payload is None:
            return None

        return {
            "failure_count": failure_count,
            "last_dor_score": dor_payload.get("score") if dor_payload else None,
            "current_phase": phase_payload.get("phase") if phase_payload else None,
        }

    async def _enrich_worker(self, entity_id: str, entity_uri: str, db: EventDB) -> dict[str, Any] | None:
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        crash_count = await db.count_events_by_entity(entity_uri, "system.worker.crashed", since=since_24h)
        last_crash_payload = await db.get_latest_event_payload(entity_uri, "system.worker.crashed")

        if crash_count == 0:
            return None

        return {
            "crash_count": crash_count,
            "last_crash_at": last_crash_payload.get("timestamp") if last_crash_payload else None,
        }
