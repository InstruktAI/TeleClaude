"""In-daemon periodic process janitor."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.paths import CHIPTUNES_SOCKET_PATH

from .guard import NeverKillGuard
from .matcher import (
    MatcherKind,
    MatchReason,
    ProcessDescriptor,
    ProcessJanitorPolicy,
    ProcessMatch,
    default_policy_specs,
    load_process_table,
    match_processes,
)
from .registry import CHIPTUNES_WORKER_OWNER

logger = get_logger(__name__)

PROCESS_REAPED_EVENT = "system.process.reaped"


@dataclass(frozen=True)
class ProcessJanitorSettings:
    """Runtime settings consumed by the janitor loop."""

    scan_interval_seconds: int
    default_signature_ttl_seconds: int
    dry_run_default: bool
    reap_revalidation_seconds: int = 3600


class OwnerLivenessProbe(Protocol):
    """Owner-specific liveness check for expired registry leases."""

    def is_live(self, owner: str, pid: int) -> bool: ...


class ChiptunesOwnerLiveness:
    """Confirm whether the registered chiptunes worker still has a live owner path."""

    def is_live(self, owner: str, pid: int) -> bool:
        del pid
        if owner != CHIPTUNES_WORKER_OWNER:
            return False
        return _unix_socket_reachable(CHIPTUNES_SOCKET_PATH)


@dataclass(frozen=True)
class _ReapResult:
    event_emitted: bool = False
    process_terminated: bool = False


class ProcessJanitorService:
    """Periodic process janitor running inside the daemon."""

    def __init__(
        self,
        db: Db,
        settings: ProcessJanitorSettings,
        shutdown_event: asyncio.Event,
        *,
        owner_liveness: OwnerLivenessProbe | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._shutdown_event = shutdown_event
        self._guard = NeverKillGuard(db)
        self._owner_liveness = owner_liveness or ChiptunesOwnerLiveness()

    async def scan_loop(self) -> None:
        """Run scans until the daemon shutdown event is set."""
        await self.seed_default_policies()
        while not self._shutdown_event.is_set():
            await self.scan_once()
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._settings.scan_interval_seconds)
            except TimeoutError:
                continue

    async def seed_default_policies(self) -> None:
        """Ensure the default leak signatures exist as policy rows."""
        for spec in default_policy_specs(
            self._settings.default_signature_ttl_seconds,
            dry_run_default=self._settings.dry_run_default,
        ):
            await self._db.upsert_process_janitor_policy(
                signature_id=str(spec["signature_id"]),
                name=str(spec["name"]),
                matcher_kind=str(spec["matcher_kind"]),
                matcher_params_json=str(spec["matcher_params_json"]),
                ttl_seconds=_int_spec_value(spec["ttl_seconds"]),
                dry_run=bool(spec["dry_run"]),
            )

    async def scan_once(self, *, now: datetime | None = None) -> int:
        """Run one scan and return the number of reap events emitted."""
        now = now or datetime.now(UTC)
        now_str = now.isoformat()
        valid_entries = await self._db.list_valid_process_spawn_registry_entries(now_str)
        registered_pids = {int(entry.pid) for entry in valid_entries}
        policies = [ProcessJanitorPolicy.from_row(row) for row in await self._db.list_process_janitor_policies()]
        processes = load_process_table()
        emitted = 0
        for match in match_processes(processes, policies, registered_pids=registered_pids):
            result = await self._handle_match(match, processes=processes, now=now)
            emitted += int(result.event_emitted)
        for entry in await self._db.list_expired_process_spawn_registry_entries(now_str):
            descriptor = _descriptor_for_pid(processes, int(entry.pid))
            if descriptor is None:
                await self._db.delete_process_spawn_registry_entry(entry.owner)
                continue
            if self._owner_liveness.is_live(entry.owner, int(entry.pid)):
                logger.debug("Process janitor kept expired live owner lease owner=%s pid=%s", entry.owner, entry.pid)
                continue
            policy = ProcessJanitorPolicy(
                signature_id="expired-spawn-lease",
                name="expired spawn registry lease",
                matcher_kind=MatcherKind.PROCESS_SIGNATURE,
                matcher_params={},
                ttl_seconds=0,
                dry_run=self._settings.dry_run_default,
            )
            result = await self._handle_match(
                ProcessMatch(
                    process=descriptor,
                    policy=policy,
                    reason=MatchReason.EXPIRED_LEASE,
                    owner=entry.owner,
                    lease_expires_at=entry.lease_expires_at,
                ),
                processes=processes,
                now=now,
            )
            emitted += int(result.event_emitted)
            if result.process_terminated:
                await self._db.delete_process_spawn_registry_entry(entry.owner)
        return emitted

    async def _handle_match(
        self, match: ProcessMatch, *, processes: list[ProcessDescriptor], now: datetime
    ) -> _ReapResult:
        decision = await self._guard.admit(match)
        if not decision.allowed:
            logger.debug("Process janitor skipped pid=%s reason=%s", match.pid, decision.reason)
            return _ReapResult()
        if _descriptor_for_pid(processes, match.pid) is None:
            return _ReapResult()
        observe_only = match.policy.dry_run
        if not observe_only:
            try:
                os.kill(match.pid, signal.SIGTERM)
            except ProcessLookupError:
                return _ReapResult()
            except PermissionError:
                logger.warning("Process janitor cannot SIGTERM pid=%s", match.pid)
                return _ReapResult()
        await self._emit_reap_event(match, observe_only=observe_only, now=now)
        return _ReapResult(event_emitted=True, process_terminated=not observe_only)

    async def _emit_reap_event(self, match: ProcessMatch, *, observe_only: bool, now: datetime) -> None:
        bucket = int(now.timestamp() // self._settings.reap_revalidation_seconds)
        idempotency_key = f"{PROCESS_REAPED_EVENT}:{match.pid}:{match.policy.signature_id}:{bucket}"
        payload: dict[str, Any] = {  # guard: loose-dict - reap event payload serialized to the event bus
            "pid": match.pid,
            "signature_id": match.policy.signature_id,
            "signature_name": match.policy.name,
            "reason": MatchReason.WOULD_REAP.value if observe_only else match.reason.value,
            "observe_only": observe_only,
        }
        if match.owner is not None:
            payload["owner"] = match.owner
        if match.lease_expires_at is not None:
            payload["lease_expires_at"] = match.lease_expires_at
        await emit_event(
            PROCESS_REAPED_EVENT,
            source="process-janitor",
            level=EventLevel.OPERATIONAL,
            domain="system",
            description="Process janitor reaped a matched process",
            payload=payload,
            visibility=EventVisibility.LOCAL,
            entity=str(match.pid),
            idempotency_key=idempotency_key,
        )


def _descriptor_for_pid(processes: list[ProcessDescriptor], pid: int) -> ProcessDescriptor | None:
    return next((process for process in processes if process.pid == pid), None)


def _int_spec_value(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("Process janitor policy ttl_seconds must be an integer")
    return value


def _unix_socket_reachable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(str(path))
            return True
    except OSError:
        return False
