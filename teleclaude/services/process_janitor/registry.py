"""Spawn registry helpers for detached platform children."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from teleclaude.core.db import (
    delete_process_spawn_registry_entry_sync,
    get_process_spawn_registry_entry_sync,
    replace_process_spawn_registry_entry_sync,
)
from teleclaude.paths import MAIN_DB_PATH

CHIPTUNES_WORKER_OWNER = "chiptunes-worker"


def lease_expiry(ttl_seconds: int) -> str:
    """Return an ISO UTC lease expiry timestamp ttl_seconds from now."""
    return (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()


@dataclass(frozen=True)
class RegistryResolution:
    """Result of resolving a prior spawn registry entry."""

    adopted_pid: int | None
    stale_pid: int | None


class ProcessSpawnRegistry:
    """Synchronous registry bridge for thread-based spawn paths."""

    def __init__(self, db_path: Path = MAIN_DB_PATH) -> None:
        self._db_path = str(db_path)

    def resolve_chiptunes(self, *, live_pids: list[int], socket_reachable: bool) -> RegistryResolution:
        """Resolve the prior chiptunes registrant before a replacement spawn."""
        entry = get_process_spawn_registry_entry_sync(self._db_path, CHIPTUNES_WORKER_OWNER)
        if socket_reachable and live_pids:
            pid = live_pids[0]
            return RegistryResolution(adopted_pid=pid, stale_pid=None)
        if entry is not None:
            return RegistryResolution(adopted_pid=None, stale_pid=entry.pid)
        if live_pids:
            return RegistryResolution(adopted_pid=None, stale_pid=live_pids[0])
        return RegistryResolution(adopted_pid=None, stale_pid=None)

    def register_chiptunes(self, pid: int, *, lease_ttl_seconds: int) -> None:
        """Register or refresh the chiptunes worker lease."""
        replace_process_spawn_registry_entry_sync(
            self._db_path,
            owner=CHIPTUNES_WORKER_OWNER,
            pid=pid,
            lease_expires_at=lease_expiry(lease_ttl_seconds),
        )

    def clear_chiptunes(self) -> None:
        """Clear the chiptunes worker registry entry."""
        delete_process_spawn_registry_entry_sync(self._db_path, CHIPTUNES_WORKER_OWNER)
