"""File-backed singleton lease for integration runtime coordination."""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal, TypedDict


class IntegrationLeaseError(RuntimeError):
    """Raised when lease state cannot be read or updated safely."""


LeaseAcquireStatus = Literal["acquired", "busy"]
LeaseRenewStatus = Literal["renewed", "missing", "stolen", "expired"]


@dataclass(frozen=True)
class LeaseRecord:
    """Durable lease record for one coordination key."""

    key: str
    owner_session_id: str
    lease_token: str
    acquired_at: str
    renewed_at: str
    expires_at: str


@dataclass(frozen=True)
class LeaseAcquireResult:
    """Lease acquisition outcome."""

    status: LeaseAcquireStatus
    lease: LeaseRecord | None
    holder: LeaseRecord | None
    replaced_stale: bool


@dataclass(frozen=True)
class LeaseRenewResult:
    """Lease renewal outcome."""

    status: LeaseRenewStatus
    lease: LeaseRecord | None


class _LeaseRecordPayload(TypedDict):
    owner_session_id: str
    lease_token: str
    acquired_at: str
    renewed_at: str
    expires_at: str


class _LeaseStatePayload(TypedDict):
    version: int
    leases: dict[str, _LeaseRecordPayload]


class IntegrationLeaseStore:
    """Atomic lease lifecycle manager backed by a durable JSON state file."""

    def __init__(
        self,
        *,
        state_path: Path,
        default_ttl_seconds: int = 120,
        lock_retry_seconds: float = 0.01,
        lock_wait_seconds: float = 5.0,
        lock_stale_seconds: int = 30,
    ) -> None:
        if default_ttl_seconds < 1:
            raise ValueError("default_ttl_seconds must be >= 1")
        self._state_path = state_path
        self._lock_path = state_path.with_suffix(f"{state_path.suffix}.lock")
        self._default_ttl_seconds = default_ttl_seconds
        self._lock_retry_seconds = lock_retry_seconds
        self._lock_wait_seconds = lock_wait_seconds
        self._lock_stale_seconds = lock_stale_seconds

    @property
    def state_path(self) -> Path:
        """Return durable lease state file path."""
        return self._state_path

    def acquire(
        self,
        *,
        key: str,
        owner_session_id: str,
        ttl_seconds: int | None = None,
        now: datetime | None = None,
    ) -> LeaseAcquireResult:
        """Acquire lease atomically or report the active holder."""
        resolved_now = _resolve_now(now)
        resolved_ttl_seconds = self._resolve_ttl_seconds(ttl_seconds)

        with self._mutation_guard():
            leases = self._load_leases()
            current = leases.get(key)
            if current is not None and not _is_expired(current, resolved_now):
                if current.owner_session_id == owner_session_id:
                    return LeaseAcquireResult(
                        status="acquired",
                        lease=current,
                        holder=current,
                        replaced_stale=False,
                    )
                return LeaseAcquireResult(
                    status="busy",
                    lease=None,
                    holder=current,
                    replaced_stale=False,
                )

            replaced_stale = current is not None
            acquired_at = resolved_now
            lease = _build_lease_record(
                key=key,
                owner_session_id=owner_session_id,
                lease_token=str(uuid.uuid4()),
                acquired_at=acquired_at,
                renewed_at=resolved_now,
                ttl_seconds=resolved_ttl_seconds,
            )
            leases[key] = lease
            self._persist_leases(leases)

            return LeaseAcquireResult(
                status="acquired",
                lease=lease,
                holder=current,
                replaced_stale=replaced_stale,
            )

    def renew(
        self,
        *,
        key: str,
        owner_session_id: str,
        lease_token: str,
        ttl_seconds: int | None = None,
        now: datetime | None = None,
    ) -> LeaseRenewResult:
        """Renew an owned lease token before expiration."""
        resolved_now = _resolve_now(now)
        resolved_ttl_seconds = self._resolve_ttl_seconds(ttl_seconds)

        with self._mutation_guard():
            leases = self._load_leases()
            current = leases.get(key)
            if current is None:
                return LeaseRenewResult(status="missing", lease=None)

            if current.owner_session_id != owner_session_id or current.lease_token != lease_token:
                return LeaseRenewResult(status="stolen", lease=current)

            if _is_expired(current, resolved_now):
                return LeaseRenewResult(status="expired", lease=current)

            renewed = _build_lease_record(
                key=key,
                owner_session_id=owner_session_id,
                lease_token=lease_token,
                acquired_at=_parse_iso8601(current.acquired_at),
                renewed_at=resolved_now,
                ttl_seconds=resolved_ttl_seconds,
            )
            leases[key] = renewed
            self._persist_leases(leases)
            return LeaseRenewResult(status="renewed", lease=renewed)

    def release(self, *, key: str, owner_session_id: str, lease_token: str) -> bool:
        """Release lease only when ownership and token still match."""
        with self._mutation_guard():
            leases = self._load_leases()
            current = leases.get(key)
            if current is None:
                return False
            if current.owner_session_id != owner_session_id or current.lease_token != lease_token:
                return False
            del leases[key]
            self._persist_leases(leases)
            return True

    def read(self, *, key: str) -> LeaseRecord | None:
        """Read current lease holder without mutating state."""
        with self._mutation_guard():
            leases = self._load_leases()
            return leases.get(key)

    def _resolve_ttl_seconds(self, ttl_seconds: int | None) -> int:
        if ttl_seconds is None:
            return self._default_ttl_seconds
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        return ttl_seconds

    @contextmanager
    def _mutation_guard(self) -> Iterator[None]:
        start = time.monotonic()
        while True:
            try:
                self._lock_path.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                self._break_stale_lock_if_needed()
                if time.monotonic() - start > self._lock_wait_seconds:
                    raise IntegrationLeaseError(f"timed out waiting for lease mutation lock: {self._lock_path}")
                time.sleep(self._lock_retry_seconds)

        try:
            yield
        finally:
            self._lock_path.rmdir()

    def _break_stale_lock_if_needed(self) -> None:
        try:
            stat_result = self._lock_path.stat()
        except FileNotFoundError:
            return

        age_seconds = time.time() - stat_result.st_mtime
        if age_seconds <= self._lock_stale_seconds:
            return

        try:
            self._lock_path.rmdir()
        except FileNotFoundError:
            return
        except OSError:
            # Another process may still hold lock and have created files inside.
            return

    def _load_leases(self) -> dict[str, LeaseRecord]:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._state_path.exists():
            return {}

        raw_text = self._state_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return {}

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise IntegrationLeaseError(f"invalid lease state JSON: {self._state_path}") from exc

        if not isinstance(payload, dict):
            raise IntegrationLeaseError(f"invalid lease state payload type: expected object at {self._state_path}")

        raw_leases = payload.get("leases")
        if raw_leases is None:
            return {}
        if not isinstance(raw_leases, dict):
            raise IntegrationLeaseError(f"invalid lease state payload: leases must be an object ({self._state_path})")

        leases: dict[str, LeaseRecord] = {}
        for raw_key, raw_record in raw_leases.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise IntegrationLeaseError("lease key must be a non-empty string")
            if not isinstance(raw_record, dict):
                raise IntegrationLeaseError(f"lease record for key {raw_key!r} must be an object")
            leases[raw_key] = _record_from_payload(raw_key, raw_record)

        return leases

    def _persist_leases(self, leases: dict[str, LeaseRecord]) -> None:
        payload: _LeaseStatePayload = {
            "version": 1,
            "leases": {
                key: {
                    "owner_session_id": value.owner_session_id,
                    "lease_token": value.lease_token,
                    "acquired_at": value.acquired_at,
                    "renewed_at": value.renewed_at,
                    "expires_at": value.expires_at,
                }
                for key, value in sorted(leases.items())
            },
        }

        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        temp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")

        with temp_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(serialized)
            file_handle.flush()
            os.fsync(file_handle.fileno())

        os.replace(temp_path, self._state_path)


def _record_from_payload(key: str, payload: dict[object, object]) -> LeaseRecord:
    owner = payload.get("owner_session_id")
    token = payload.get("lease_token")
    acquired_at = payload.get("acquired_at")
    renewed_at = payload.get("renewed_at")
    expires_at = payload.get("expires_at")

    for field_name, value in (
        ("owner_session_id", owner),
        ("lease_token", token),
        ("acquired_at", acquired_at),
        ("renewed_at", renewed_at),
        ("expires_at", expires_at),
    ):
        if not isinstance(value, str) or not value.strip():
            raise IntegrationLeaseError(f"lease field {field_name!r} for key {key!r} must be a non-empty string")

    parsed_acquired = _parse_iso8601(acquired_at)
    parsed_renewed = _parse_iso8601(renewed_at)
    parsed_expires = _parse_iso8601(expires_at)
    if parsed_acquired > parsed_renewed:
        raise IntegrationLeaseError(f"lease key {key!r} has acquired_at after renewed_at")
    if parsed_renewed > parsed_expires:
        raise IntegrationLeaseError(f"lease key {key!r} has renewed_at after expires_at")

    return LeaseRecord(
        key=key,
        owner_session_id=owner,
        lease_token=token,
        acquired_at=acquired_at,
        renewed_at=renewed_at,
        expires_at=expires_at,
    )


def _build_lease_record(
    *,
    key: str,
    owner_session_id: str,
    lease_token: str,
    acquired_at: datetime,
    renewed_at: datetime,
    ttl_seconds: int,
) -> LeaseRecord:
    expires_at = renewed_at + timedelta(seconds=ttl_seconds)
    return LeaseRecord(
        key=key,
        owner_session_id=owner_session_id,
        lease_token=lease_token,
        acquired_at=_format_iso8601(acquired_at),
        renewed_at=_format_iso8601(renewed_at),
        expires_at=_format_iso8601(expires_at),
    )


def _resolve_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(UTC)


def _is_expired(record: LeaseRecord, now: datetime) -> bool:
    expires_at = _parse_iso8601(record.expires_at)
    return expires_at <= now


def _parse_iso8601(raw_value: str) -> datetime:
    normalized = raw_value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise IntegrationLeaseError(f"timestamp must include timezone offset: {raw_value!r}")
    return parsed.astimezone(UTC)


def _format_iso8601(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")
