"""Lightweight observability for TUI animation performance."""
# pylint: disable=too-many-instance-attributes

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class AnimationPerfSnapshot:
    """Point-in-time summary of recent animation performance."""

    tick_count: int
    changed_tick_count: int
    recent_avg_total_ms: float
    recent_max_total_ms: float
    recent_avg_update_ms: float
    recent_avg_build_ms: float
    header_entity_count: int
    consecutive_slow_frames: int


@dataclass
class AnimationPerfTracker:
    """Bounded tracker for animation tick cost and drift."""

    slow_frame_threshold_ms: float = 40.0
    warning_interval_ticks: int = 120
    baseline_interval_ticks: int = 240
    _recent_total_ms: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    _recent_update_ms: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    _recent_build_ms: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    tick_count: int = 0
    changed_tick_count: int = 0
    consecutive_slow_frames: int = 0
    _last_warning_tick: int = 0
    _last_baseline_tick: int = 0

    def record_tick(
        self,
        *,
        changed: bool,
        total_ms: float,
        update_ms: float,
        build_ms: float,
    ) -> None:
        """Record a single animation tick."""
        self.tick_count += 1
        if changed:
            self.changed_tick_count += 1
        self._recent_total_ms.append(total_ms)
        self._recent_update_ms.append(update_ms)
        self._recent_build_ms.append(build_ms)
        if total_ms >= self.slow_frame_threshold_ms:
            self.consecutive_slow_frames += 1
        else:
            self.consecutive_slow_frames = 0

    def should_warn(self) -> bool:
        """Return whether recent animation cost warrants a diagnostic log."""
        if self.consecutive_slow_frames >= 3:
            return True
        return self.tick_count - self._last_warning_tick >= self.warning_interval_ticks

    def mark_warned(self) -> None:
        """Advance the warning watermark."""
        self._last_warning_tick = self.tick_count

    def should_emit_baseline(self) -> bool:
        """Return whether it is time for a low-frequency baseline snapshot."""
        return self.tick_count - self._last_baseline_tick >= self.baseline_interval_ticks

    def mark_baseline_emitted(self) -> None:
        """Advance the baseline watermark."""
        self._last_baseline_tick = self.tick_count

    def snapshot(self, *, header_entity_count: int) -> AnimationPerfSnapshot:
        """Build a bounded summary for log emission."""
        return AnimationPerfSnapshot(
            tick_count=self.tick_count,
            changed_tick_count=self.changed_tick_count,
            recent_avg_total_ms=_avg(self._recent_total_ms),
            recent_max_total_ms=max(self._recent_total_ms, default=0.0),
            recent_avg_update_ms=_avg(self._recent_update_ms),
            recent_avg_build_ms=_avg(self._recent_build_ms),
            header_entity_count=header_entity_count,
            consecutive_slow_frames=self.consecutive_slow_frames,
        )


def _avg(values: deque[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
