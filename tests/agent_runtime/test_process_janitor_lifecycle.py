"""Functional coverage for daemon-owned process lifecycle state and scanning."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from teleclaude.core.db import Db
from teleclaude.core.db_models import ProcessJanitorPolicy as ProcessJanitorPolicyRow
from teleclaude.core.db_models import ProcessSpawnRegistryEntry
from teleclaude.services.process_janitor import guard as guard_mod
from teleclaude.services.process_janitor import service as service_mod
from teleclaude.services.process_janitor.guard import NeverKillGuard
from teleclaude.services.process_janitor.matcher import (
    MatcherKind,
    ProcessDescriptor,
    ProcessJanitorPolicy,
    ProcessMatch,
    match_processes,
)
from teleclaude.services.process_janitor.registry import CHIPTUNES_WORKER_OWNER
from teleclaude.services.process_janitor.service import ProcessJanitorService, ProcessJanitorSettings

pytestmark = pytest.mark.functional

_SIGNATURE_ID = "custom-leak"
_SIGNATURE_NAME = "custom leak"
_OWNER = "worker"
_SOURCE = "process-janitor"
_REAP_EVENT = "system.process.reaped"
_LIVE_SESSION_TREE = "live-session-tree"
_VALID_LEASE = "valid-lease"
_UID_MISMATCH = "uid-mismatch"
_IDENTITY_UNRESOLVED = "process-identity-unresolved"


def _past(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _future(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _descriptor(pid: int, *, age_seconds: int, cmdline: tuple[str, ...]) -> ProcessDescriptor:
    return ProcessDescriptor(
        pid=pid,
        ppid=1,
        create_time=datetime.now(UTC).timestamp() - age_seconds,
        cmdline=cmdline,
        uid=0,
    )


@pytest.mark.asyncio
async def test_process_lifecycle_db_round_trips_policy_and_unique_owner() -> None:
    """Policy rows and unique-owner registry rows persist at the daemon DB boundary."""
    db = Db(":memory:")
    await db.initialize()
    await db.upsert_process_janitor_policy(
        signature_id=_SIGNATURE_ID,
        name=_SIGNATURE_NAME,
        matcher_kind=MatcherKind.PROCESS_SIGNATURE.value,
        matcher_params_json=json.dumps({"all_cmdline_tokens": ["telec"]}),
        ttl_seconds=60,
        dry_run=True,
    )
    [policy] = await db.list_process_janitor_policies()
    first_previous = await db.replace_process_spawn_registry_entry(
        owner=_OWNER,
        pid=111,
        lease_expires_at=_future(60),
        registered_at=_past(1),
    )
    second_previous = await db.replace_process_spawn_registry_entry(
        owner=_OWNER,
        pid=222,
        lease_expires_at=_future(120),
        registered_at=_past(1),
    )
    current = await db.get_process_spawn_registry_entry(_OWNER)
    expired = await db.list_expired_process_spawn_registry_entries(datetime.now(UTC).isoformat())

    assert policy.signature_id == _SIGNATURE_ID
    assert policy.dry_run == 1
    assert first_previous is None
    assert second_previous is not None
    assert second_previous.pid == 111
    assert current is not None
    assert current.pid == 222
    assert expired == []
    await db.close()


def test_matcher_honors_data_policy_without_code_change() -> None:
    """A new policy row is enough to make a matching stale process selectable."""
    process = _descriptor(111, age_seconds=120, cmdline=("python", "-m", "custom.leak"))
    policy = ProcessJanitorPolicy(
        signature_id=_SIGNATURE_ID,
        name=_SIGNATURE_NAME,
        matcher_kind=MatcherKind.PROCESS_SIGNATURE,
        matcher_params={"all_cmdline_tokens": ["custom.leak"]},
        ttl_seconds=60,
        dry_run=False,
    )

    [match] = match_processes([process], [policy], registered_pids=set())

    assert match.pid == 111
    assert match.policy.signature_id == _SIGNATURE_ID


@pytest.mark.asyncio
async def test_never_kill_guard_rejects_daemon_pid() -> None:
    """The daemon pid is rejected even after a positive signature match."""
    db = Db(":memory:")
    await db.initialize()
    guard = NeverKillGuard(db)
    match = ProcessMatch(
        process=_descriptor(guard._own_pid, age_seconds=120, cmdline=("python",)),
        policy=ProcessJanitorPolicy(
            signature_id=_SIGNATURE_ID,
            name=_SIGNATURE_NAME,
            matcher_kind=MatcherKind.PROCESS_SIGNATURE,
            matcher_params={},
            ttl_seconds=60,
            dry_run=False,
        ),
    )

    decision = await guard.admit(match)

    assert decision.allowed is False
    await db.close()


class _GuardDb:
    def __init__(
        self,
        *,
        sessions: list[SimpleNamespace] | None = None,
        valid_entries: list[ProcessSpawnRegistryEntry] | None = None,
    ) -> None:
        self.sessions = sessions or []
        self.valid_entries = valid_entries or []

    async def get_active_sessions(self) -> list[SimpleNamespace]:
        return self.sessions

    async def list_valid_process_spawn_registry_entries(self, _now: str) -> list[ProcessSpawnRegistryEntry]:
        return self.valid_entries


class _FakePsutilProcess:
    def __init__(self, pid: int, *, uid: int | None = None, children: list[SimpleNamespace] | None = None) -> None:
        self.pid = pid
        self._uid = os.getuid() if uid is None else uid
        self._children = children or []

    def uids(self) -> SimpleNamespace:
        return SimpleNamespace(real=self._uid, effective=self._uid, saved=self._uid)

    def children(self, *, recursive: bool) -> list[SimpleNamespace]:
        del recursive
        return self._children


def _matching_process(candidate_pid: int) -> ProcessMatch:
    return ProcessMatch(
        process=_descriptor(candidate_pid, age_seconds=120, cmdline=("python",)),
        policy=ProcessJanitorPolicy(
            signature_id=_SIGNATURE_ID,
            name=_SIGNATURE_NAME,
            matcher_kind=MatcherKind.PROCESS_SIGNATURE,
            matcher_params={},
            ttl_seconds=60,
            dry_run=False,
        ),
    )


@pytest.mark.asyncio
async def test_never_kill_guard_rejects_live_session_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process in a live session pane tree is denied even when signatures match."""
    candidate_pid = 91234
    pane_pid = 91230
    session_name = "teleclaude-session"
    guard = NeverKillGuard(cast(Db, _GuardDb(sessions=[SimpleNamespace(tmux_session_name=session_name)])))

    def _process(pid: int) -> _FakePsutilProcess:
        if pid == pane_pid:
            return _FakePsutilProcess(pid, children=[SimpleNamespace(pid=candidate_pid)])
        return _FakePsutilProcess(pid)

    async def _pane_pid(_tmux_name: str) -> int:
        return pane_pid

    monkeypatch.setattr(guard_mod.psutil, "Process", _process)
    monkeypatch.setattr(guard_mod.os, "getpgid", lambda _pid: guard._own_pgrp + 1)
    monkeypatch.setattr(guard_mod.tmux_bridge, "get_pane_pid", _pane_pid)

    decision = await guard.admit(_matching_process(candidate_pid))

    assert decision.allowed is False
    assert decision.reason == _LIVE_SESSION_TREE


@pytest.mark.asyncio
async def test_never_kill_guard_rejects_valid_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """A live registry lease protects its registrant from signature reaping."""
    candidate_pid = 91235
    entry = ProcessSpawnRegistryEntry(
        owner=_OWNER,
        pid=candidate_pid,
        lease_expires_at=_future(60),
        registered_at=_past(1),
    )
    guard = NeverKillGuard(cast(Db, _GuardDb(valid_entries=[entry])))

    monkeypatch.setattr(guard_mod.psutil, "Process", lambda pid: _FakePsutilProcess(pid))
    monkeypatch.setattr(guard_mod.os, "getpgid", lambda _pid: guard._own_pgrp + 1)

    decision = await guard.admit(_matching_process(candidate_pid))

    assert decision.allowed is False
    assert decision.reason == _VALID_LEASE


@pytest.mark.asyncio
async def test_never_kill_guard_rejects_unresolved_process_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process identity read failure defaults to deny."""
    candidate_pid = 91236
    guard = NeverKillGuard(cast(Db, _GuardDb()))

    def _raise(_pid: int) -> object:
        raise guard_mod.psutil.NoSuchProcess(candidate_pid)

    monkeypatch.setattr(guard_mod.psutil, "Process", _raise)

    decision = await guard.admit(_matching_process(candidate_pid))

    assert decision.allowed is False
    assert decision.reason == _IDENTITY_UNRESOLVED


@pytest.mark.asyncio
async def test_never_kill_guard_rejects_foreign_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process owned by another uid is never reaped."""
    candidate_pid = 91237
    guard = NeverKillGuard(cast(Db, _GuardDb()))

    monkeypatch.setattr(guard_mod.psutil, "Process", lambda pid: _FakePsutilProcess(pid, uid=os.getuid() + 1))

    decision = await guard.admit(_matching_process(candidate_pid))

    assert decision.allowed is False
    assert decision.reason == _UID_MISMATCH


@dataclass
class _AllowingGuard:
    async def admit(self, _match: ProcessMatch) -> Any:
        return type("Decision", (), {"allowed": True, "reason": "allowed"})()


@dataclass
class _DenyingGuard:
    reason: str

    async def admit(self, _match: ProcessMatch) -> Any:
        return type("Decision", (), {"allowed": False, "reason": self.reason})()


@dataclass
class _StaticOwnerLiveness:
    live: bool

    def is_live(self, _owner: str, _pid: int) -> bool:
        return self.live


class _ServiceDb:
    def __init__(
        self,
        policy: ProcessJanitorPolicyRow | None = None,
        *,
        expired_entries: list[ProcessSpawnRegistryEntry] | None = None,
    ) -> None:
        self.policies = [] if policy is None else [policy]
        self.expired_entries = expired_entries or []
        self.deleted_owners: list[str] = []

    async def upsert_process_janitor_policy(self, **_kwargs: object) -> None:
        return None

    async def list_valid_process_spawn_registry_entries(self, _now: str) -> list[ProcessSpawnRegistryEntry]:
        return []

    async def list_expired_process_spawn_registry_entries(self, _now: str) -> list[ProcessSpawnRegistryEntry]:
        return self.expired_entries

    async def list_process_janitor_policies(self) -> list[ProcessJanitorPolicyRow]:
        return self.policies

    async def delete_process_spawn_registry_entry(self, owner: str) -> None:
        self.deleted_owners.append(owner)


@pytest.mark.asyncio
async def test_dry_run_scan_emits_observe_event_without_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run policies emit an observable would-reap event and leave the process alive."""
    policy = ProcessJanitorPolicyRow(
        signature_id=_SIGNATURE_ID,
        name=_SIGNATURE_NAME,
        matcher_kind=MatcherKind.PROCESS_SIGNATURE.value,
        matcher_params_json=json.dumps({"all_cmdline_tokens": ["custom.leak"]}),
        ttl_seconds=60,
        enabled=1,
        dry_run=1,
    )
    process = _descriptor(333, age_seconds=120, cmdline=("python", "-m", "custom.leak"))
    killed: list[int] = []
    emitted: list[dict[str, object]] = []

    async def _capture_emit_event(event: str, source: str, **kwargs: object) -> str:
        emitted.append({"event": event, "source": source, **kwargs})
        return "1-0"

    monkeypatch.setattr(service_mod, "load_process_table", lambda: [process])
    monkeypatch.setattr(service_mod.os, "kill", lambda pid, _signal: killed.append(pid))
    monkeypatch.setattr(service_mod, "emit_event", _capture_emit_event)
    service = ProcessJanitorService(
        cast(Db, _ServiceDb(policy)),
        ProcessJanitorSettings(scan_interval_seconds=60, default_signature_ttl_seconds=60, dry_run_default=True),
        cast(Any, object()),
    )
    service._guard = _AllowingGuard()

    emitted_count = await service.scan_once()

    assert emitted_count == 1
    assert killed == []
    [event] = emitted
    assert event["event"] == _REAP_EVENT
    assert event["source"] == _SOURCE
    payload = event["payload"]
    assert isinstance(payload, dict)
    assert payload["pid"] == 333
    assert payload["observe_only"] is True


@pytest.mark.asyncio
async def test_expired_live_owned_chiptunes_worker_is_not_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lease expiry alone is insufficient when the chiptunes owner is still reachable."""
    entry = ProcessSpawnRegistryEntry(
        owner=CHIPTUNES_WORKER_OWNER,
        pid=444,
        lease_expires_at=_past(1),
        registered_at=_past(3600),
    )
    db = _ServiceDb(expired_entries=[entry])
    process = _descriptor(444, age_seconds=3600, cmdline=("python", "-m", "teleclaude.chiptunes.worker"))
    killed: list[int] = []
    emitted: list[dict[str, object]] = []

    async def _capture_emit_event(event: str, source: str, **kwargs: object) -> str:
        emitted.append({"event": event, "source": source, **kwargs})
        return "1-0"

    monkeypatch.setattr(service_mod, "load_process_table", lambda: [process])
    monkeypatch.setattr(service_mod.os, "kill", lambda pid, _signal: killed.append(pid))
    monkeypatch.setattr(service_mod, "emit_event", _capture_emit_event)
    service = ProcessJanitorService(
        cast(Db, db),
        ProcessJanitorSettings(scan_interval_seconds=60, default_signature_ttl_seconds=60, dry_run_default=False),
        cast(Any, object()),
        owner_liveness=_StaticOwnerLiveness(True),
    )
    service._guard = _AllowingGuard()

    emitted_count = await service.scan_once()

    assert emitted_count == 0
    assert killed == []
    assert emitted == []
    assert db.deleted_owners == []


@pytest.mark.asyncio
async def test_expired_lease_row_survives_guard_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guard-rejected expired lease is left intact for the next scan."""
    entry = ProcessSpawnRegistryEntry(
        owner=_OWNER,
        pid=445,
        lease_expires_at=_past(1),
        registered_at=_past(3600),
    )
    db = _ServiceDb(expired_entries=[entry])
    process = _descriptor(445, age_seconds=3600, cmdline=("python", "-m", "custom.leak"))
    killed: list[int] = []

    monkeypatch.setattr(service_mod, "load_process_table", lambda: [process])
    monkeypatch.setattr(service_mod.os, "kill", lambda pid, _signal: killed.append(pid))
    service = ProcessJanitorService(
        cast(Db, db),
        ProcessJanitorSettings(scan_interval_seconds=60, default_signature_ttl_seconds=60, dry_run_default=False),
        cast(Any, object()),
        owner_liveness=_StaticOwnerLiveness(False),
    )
    service._guard = _DenyingGuard(_VALID_LEASE)

    emitted_count = await service.scan_once()

    assert emitted_count == 0
    assert killed == []
    assert db.deleted_owners == []
