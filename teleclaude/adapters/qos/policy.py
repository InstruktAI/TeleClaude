"""Adapter output QoS policies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from teleclaude.config import config


def _ceil_to_step(value: float, step_s: float) -> float:
    if value <= 0:
        return 0.0
    if step_s <= 0:
        return value
    units = math.ceil(value / step_s)
    rounded = units * step_s
    return round(rounded, 3)


def _normalize_qos_mode(raw: str | None, default: "OutputQoSMode") -> "OutputQoSMode":
    text = (raw or "").strip().lower()
    if text == OutputQoSMode.STRICT.value:
        return OutputQoSMode.STRICT
    if text == OutputQoSMode.COALESCE_ONLY.value:
        return OutputQoSMode.COALESCE_ONLY
    if text == OutputQoSMode.OFF.value:
        return OutputQoSMode.OFF
    return default


class OutputQoSMode(str, Enum):
    OFF = "off"
    COALESCE_ONLY = "coalesce_only"
    STRICT = "strict"


class OutputPriority(str, Enum):
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class CadenceDecision:
    effective_output_mpm: int
    global_tick_s: float
    session_tick_s: float


class OutputQoSPolicy(Protocol):
    """Policy contract used by the output scheduler."""

    @property
    def adapter_key(self) -> str: ...

    @property
    def mode(self) -> OutputQoSMode: ...

    @property
    def active_emitter_window_s(self) -> float: ...

    @property
    def active_emitter_ema_alpha(self) -> float: ...

    def classify_priority(self, *, is_final: bool, completion_critical: bool = False) -> OutputPriority:
        """Map an output event to a scheduler priority class."""
        ...

    def should_coalesce(self, priority: OutputPriority) -> bool:
        """Return True when payloads of this class should be latest-only."""
        ...

    def compute_cadence(self, *, active_emitting_sessions: int, smoothed_active_emitters: float) -> CadenceDecision:
        """Compute dispatch cadence for the current activity level."""
        ...


@dataclass(frozen=True)
class TelegramOutputPolicy:
    """Strict Telegram pacing policy with active-emitter scaling."""

    enabled: bool
    group_mpm: int
    output_budget_ratio: float
    reserve_mpm: int
    min_session_tick_s: float
    max_session_tick_s: float | None
    active_emitter_window_s: float
    active_emitter_ema_alpha: float
    rounding_ms: int

    adapter_key: str = "telegram"

    @property
    def mode(self) -> OutputQoSMode:
        return OutputQoSMode.STRICT if self.enabled else OutputQoSMode.OFF

    @property
    def rounding_s(self) -> float:
        if self.rounding_ms <= 0:
            return 0.1
        return self.rounding_ms / 1000.0

    def classify_priority(self, *, is_final: bool, completion_critical: bool = False) -> OutputPriority:
        if is_final or completion_critical:
            return OutputPriority.HIGH
        return OutputPriority.NORMAL

    def should_coalesce(self, priority: OutputPriority) -> bool:
        return priority == OutputPriority.NORMAL and self.mode != OutputQoSMode.OFF

    def compute_cadence(self, *, active_emitting_sessions: int, smoothed_active_emitters: float) -> CadenceDecision:
        if self.mode != OutputQoSMode.STRICT:
            return CadenceDecision(effective_output_mpm=0, global_tick_s=0.0, session_tick_s=0.0)

        group_mpm = max(1, int(self.group_mpm))
        reserve_mpm = max(0, int(self.reserve_mpm))
        ratio = max(0.0, float(self.output_budget_ratio))

        budget_cap = max(1, group_mpm - reserve_mpm)
        budget_target = max(1, math.floor(group_mpm * ratio))
        effective_output_mpm = max(1, min(budget_cap, budget_target))

        global_tick_s = _ceil_to_step(60.0 / float(effective_output_mpm), self.rounding_s)

        active_raw = max(1.0, float(active_emitting_sessions))
        active_smoothed = max(1.0, float(smoothed_active_emitters))
        active = max(active_raw, active_smoothed)

        session_tick_raw = max(float(self.min_session_tick_s), global_tick_s * active)
        if self.max_session_tick_s is not None:
            session_tick_raw = min(session_tick_raw, float(self.max_session_tick_s))
        session_tick_s = _ceil_to_step(session_tick_raw, self.rounding_s)

        return CadenceDecision(
            effective_output_mpm=effective_output_mpm,
            global_tick_s=global_tick_s,
            session_tick_s=session_tick_s,
        )


@dataclass(frozen=True)
class DiscordOutputPolicy:
    """Discord starts in coalesce-only mode unless configured otherwise."""

    mode: OutputQoSMode
    active_emitter_window_s: float = 10.0
    active_emitter_ema_alpha: float = 0.2
    adapter_key: str = "discord"

    def classify_priority(self, *, is_final: bool, completion_critical: bool = False) -> OutputPriority:
        if is_final or completion_critical:
            return OutputPriority.HIGH
        return OutputPriority.NORMAL

    def should_coalesce(self, priority: OutputPriority) -> bool:
        if self.mode == OutputQoSMode.OFF:
            return False
        return priority == OutputPriority.NORMAL

    def compute_cadence(self, *, active_emitting_sessions: int, smoothed_active_emitters: float) -> CadenceDecision:
        if self.mode != OutputQoSMode.STRICT:
            return CadenceDecision(effective_output_mpm=0, global_tick_s=0.0, session_tick_s=0.0)

        active = max(1.0, float(active_emitting_sessions), float(smoothed_active_emitters))
        session_tick_s = max(0.1, round(0.5 * active, 2))
        return CadenceDecision(effective_output_mpm=120, global_tick_s=0.5, session_tick_s=session_tick_s)


@dataclass(frozen=True)
class WhatsAppOutputPolicy:
    """WhatsApp output pacing stays disabled until limits are validated."""

    mode: OutputQoSMode
    active_emitter_window_s: float = 10.0
    active_emitter_ema_alpha: float = 0.2
    adapter_key: str = "whatsapp"

    def classify_priority(self, *, is_final: bool, completion_critical: bool = False) -> OutputPriority:
        if is_final or completion_critical:
            return OutputPriority.HIGH
        return OutputPriority.NORMAL

    def should_coalesce(self, priority: OutputPriority) -> bool:
        if self.mode == OutputQoSMode.OFF:
            return False
        return priority == OutputPriority.NORMAL

    def compute_cadence(self, *, active_emitting_sessions: int, smoothed_active_emitters: float) -> CadenceDecision:
        _ = active_emitting_sessions
        _ = smoothed_active_emitters
        return CadenceDecision(effective_output_mpm=0, global_tick_s=0.0, session_tick_s=0.0)


def build_output_policy(adapter_key: str) -> OutputQoSPolicy:
    """Build adapter policy from runtime config."""
    if adapter_key == "telegram":
        telegram_cfg = getattr(config, "telegram", None)
        qos_cfg = getattr(telegram_cfg, "qos", None)
        return TelegramOutputPolicy(
            enabled=bool(getattr(qos_cfg, "enabled", True)),
            group_mpm=int(getattr(qos_cfg, "group_mpm", 20)),
            output_budget_ratio=float(getattr(qos_cfg, "output_budget_ratio", 0.8)),
            reserve_mpm=int(getattr(qos_cfg, "reserve_mpm", 4)),
            min_session_tick_s=float(getattr(qos_cfg, "min_session_tick_s", 3.0)),
            max_session_tick_s=getattr(qos_cfg, "max_session_tick_s", None),
            active_emitter_window_s=float(getattr(qos_cfg, "active_emitter_window_s", 10.0)),
            active_emitter_ema_alpha=float(getattr(qos_cfg, "active_emitter_ema_alpha", 0.2)),
            rounding_ms=int(getattr(qos_cfg, "rounding_ms", 100)),
        )

    if adapter_key == "discord":
        discord_cfg = getattr(config, "discord", None)
        qos_cfg = getattr(discord_cfg, "qos", None)
        mode = _normalize_qos_mode(getattr(qos_cfg, "mode", None), OutputQoSMode.COALESCE_ONLY)
        return DiscordOutputPolicy(mode=mode)

    if adapter_key == "whatsapp":
        whatsapp_cfg = getattr(config, "whatsapp", None)
        qos_cfg = getattr(whatsapp_cfg, "qos", None)
        mode = _normalize_qos_mode(getattr(qos_cfg, "mode", None), OutputQoSMode.OFF)
        return WhatsAppOutputPolicy(mode=mode)

    return WhatsAppOutputPolicy(mode=OutputQoSMode.OFF, adapter_key=adapter_key)  # type: ignore[arg-type]
