"""Unit tests for teleclaude.adapters.qos.action_throttler."""

from __future__ import annotations

from teleclaude.adapters.qos.action_throttler import AdapterActionThrottler


class TestAdapterActionThrottler:
    def test_allows_first_action_attempt(self) -> None:
        throttler = AdapterActionThrottler()

        allowed = throttler.allow("discord:sess-1:typing", min_interval_s=10.0, now=100.0)

        assert allowed is True

    def test_blocks_repeated_attempt_inside_interval(self) -> None:
        throttler = AdapterActionThrottler()
        throttler.allow("discord:sess-1:typing", min_interval_s=10.0, now=100.0)

        allowed = throttler.allow("discord:sess-1:typing", min_interval_s=10.0, now=105.0)

        assert allowed is False

    def test_allows_repeated_attempt_after_interval(self) -> None:
        throttler = AdapterActionThrottler()
        throttler.allow("discord:sess-1:typing", min_interval_s=10.0, now=100.0)

        allowed = throttler.allow("discord:sess-1:typing", min_interval_s=10.0, now=110.0)

        assert allowed is True

    def test_tracks_distinct_action_kinds_independently(self) -> None:
        throttler = AdapterActionThrottler()
        throttler.allow("discord:sess-1:typing", min_interval_s=10.0, now=100.0)

        allowed = throttler.allow("discord:sess-1:badge", min_interval_s=10.0, now=101.0)

        assert allowed is True

    def test_non_positive_interval_never_throttles(self) -> None:
        throttler = AdapterActionThrottler()
        throttler.allow("discord:sess-1:typing", min_interval_s=0.0, now=100.0)

        allowed = throttler.allow("discord:sess-1:typing", min_interval_s=0.0, now=100.1)

        assert allowed is True
