"""Characterization tests for teleclaude.core.inbound_queue."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude.core.inbound_queue import (
    InboundQueueManager,
    _backoff_for_attempt,
    get_inbound_queue_manager,
    init_inbound_queue_manager,
    reset_inbound_queue_manager,
)


class TestBackoffForAttempt:
    @pytest.mark.unit
    def test_attempt_zero_returns_first_value(self):
        result = _backoff_for_attempt(0)
        assert result > 0

    @pytest.mark.unit
    def test_backoff_increases_with_attempts(self):
        b0 = _backoff_for_attempt(0)
        b1 = _backoff_for_attempt(1)
        b2 = _backoff_for_attempt(2)
        assert b0 <= b1 <= b2

    @pytest.mark.unit
    def test_large_attempt_capped_at_max(self):
        b_large = _backoff_for_attempt(1000)
        b_cap = _backoff_for_attempt(6)  # Last index in schedule
        assert b_large == b_cap


class TestInboundQueueManagerSingleton:
    @pytest.mark.unit
    def test_get_before_init_raises(self):
        reset_inbound_queue_manager()
        with pytest.raises(RuntimeError):
            get_inbound_queue_manager()

    @pytest.mark.unit
    def test_init_returns_manager(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        manager = init_inbound_queue_manager(deliver_fn)
        assert isinstance(manager, InboundQueueManager)
        reset_inbound_queue_manager()

    @pytest.mark.unit
    def test_double_init_without_force_raises(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        init_inbound_queue_manager(deliver_fn)
        with pytest.raises(RuntimeError):
            init_inbound_queue_manager(deliver_fn)
        reset_inbound_queue_manager()

    @pytest.mark.unit
    def test_double_init_with_force_succeeds(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        init_inbound_queue_manager(deliver_fn)
        manager = init_inbound_queue_manager(deliver_fn, force=True)
        assert manager is not None
        reset_inbound_queue_manager()

    @pytest.mark.unit
    def test_get_after_init_returns_manager(self):
        reset_inbound_queue_manager()
        deliver_fn = AsyncMock()
        init_inbound_queue_manager(deliver_fn)
        manager = get_inbound_queue_manager()
        assert isinstance(manager, InboundQueueManager)
        reset_inbound_queue_manager()
