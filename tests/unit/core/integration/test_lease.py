"""Characterization tests for teleclaude.core.integration.lease."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teleclaude.core.integration.lease import (
    IntegrationLeaseStore,
    LeaseRecord,
)

_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_KEY = "integration/main"
_OWNER = "session-abc"


def _make_store(tmp_path: Path, **kwargs: object) -> IntegrationLeaseStore:
    return IntegrationLeaseStore(state_path=tmp_path / "leases.json", **kwargs)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_store_rejects_zero_ttl(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        IntegrationLeaseStore(state_path=tmp_path / "l.json", default_ttl_seconds=0)


# ---------------------------------------------------------------------------
# acquire
# ---------------------------------------------------------------------------


def test_acquire_returns_acquired_status(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    result = store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    assert result.status == "acquired"
    assert result.lease is not None
    assert result.lease.owner_session_id == _OWNER


def test_acquire_by_same_owner_returns_acquired(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    result = store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    assert result.status == "acquired"


def test_acquire_by_different_owner_returns_busy(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    result = store.acquire(key=_KEY, owner_session_id="other-session", now=_NOW)
    assert result.status == "busy"
    assert result.holder is not None
    assert result.holder.owner_session_id == _OWNER


def test_acquire_replaces_expired_lease(tmp_path: Path) -> None:
    store = _make_store(tmp_path, default_ttl_seconds=1)
    store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    future = _NOW + timedelta(seconds=5)
    result = store.acquire(key=_KEY, owner_session_id="other-session", now=future)
    assert result.status == "acquired"
    assert result.replaced_stale is True


# ---------------------------------------------------------------------------
# renew
# ---------------------------------------------------------------------------


def test_renew_extends_lease(tmp_path: Path) -> None:
    store = _make_store(tmp_path, default_ttl_seconds=60)
    acq = store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    assert acq.lease is not None
    result = store.renew(
        key=_KEY,
        owner_session_id=_OWNER,
        lease_token=acq.lease.lease_token,
        now=_NOW + timedelta(seconds=30),
    )
    assert result.status == "renewed"


def test_renew_returns_missing_when_no_lease(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    result = store.renew(key=_KEY, owner_session_id=_OWNER, lease_token="fake-token", now=_NOW)
    assert result.status == "missing"


def test_renew_returns_stolen_when_token_mismatch(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    result = store.renew(key=_KEY, owner_session_id=_OWNER, lease_token="wrong-token", now=_NOW)
    assert result.status == "stolen"


def test_renew_returns_expired_when_ttl_elapsed(tmp_path: Path) -> None:
    store = _make_store(tmp_path, default_ttl_seconds=1)
    acq = store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    assert acq.lease is not None
    future = _NOW + timedelta(seconds=5)
    result = store.renew(
        key=_KEY,
        owner_session_id=_OWNER,
        lease_token=acq.lease.lease_token,
        now=future,
    )
    assert result.status == "expired"


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def test_release_removes_lease(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    acq = store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    assert acq.lease is not None
    released = store.release(key=_KEY, owner_session_id=_OWNER, lease_token=acq.lease.lease_token)
    assert released is True
    assert store.read(key=_KEY) is None


def test_release_returns_false_when_token_mismatch(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    released = store.release(key=_KEY, owner_session_id=_OWNER, lease_token="wrong")
    assert released is False


def test_release_returns_false_when_no_lease(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    released = store.release(key=_KEY, owner_session_id=_OWNER, lease_token="any")
    assert released is False


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_returns_current_holder(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    record = store.read(key=_KEY)
    assert record is not None
    assert isinstance(record, LeaseRecord)
    assert record.owner_session_id == _OWNER


def test_read_returns_none_when_absent(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.read(key=_KEY) is None


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_lease_persists_across_reload(tmp_path: Path) -> None:
    path = tmp_path / "leases.json"
    s1 = IntegrationLeaseStore(state_path=path)
    s1.acquire(key=_KEY, owner_session_id=_OWNER, now=_NOW)
    s2 = IntegrationLeaseStore(state_path=path)
    record = s2.read(key=_KEY)
    assert record is not None
    assert record.owner_session_id == _OWNER
