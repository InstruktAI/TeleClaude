"""Adapter output QoS policy definitions.

Each adapter has a policy that controls coalescing strategy, pacing budget,
and priority class mapping. This module provides the policy contract and
adapter-specific policy factories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.config import DiscordQoSConfig, TelegramQoSConfig, WhatsAppQoSConfig


@dataclass(frozen=True, slots=True)
class _QoSBudget:
    """Budget-related QoS parameters."""

    group_mpm: int = 20
    output_budget_ratio: float = 0.8
    reserve_mpm: int = 4


@dataclass(frozen=True, slots=True)
class _QoSCadence:
    """Cadence-related QoS parameters."""

    min_session_tick_s: float = 3.0
    active_emitter_window_s: float = 10.0
    active_emitter_ema_alpha: float = 0.2
    rounding_ms: int = 100


class QoSPolicy:
    """Output QoS policy parameters for an adapter.

    Attributes:
        adapter_key: Adapter identifier (e.g. "telegram", "discord").
        mode: Dispatch mode: "off" | "coalesce_only" | "strict".
        group_mpm: Platform group message-per-minute budget (strict mode only).
        output_budget_ratio: Fraction of group_mpm available for output updates.
        reserve_mpm: mpm reserved for non-output messages (commands, footers).
        min_session_tick_s: Minimum seconds between dispatches per session.
        active_emitter_window_s: Seconds a session remains counted as active after last emit.
        active_emitter_ema_alpha: EMA smoothing factor for active session count (0..1).
        rounding_ms: Cadence rounding granularity in milliseconds.
    """

    __slots__ = ("_budget", "_cadence", "adapter_key", "mode")

    def __init__(self, adapter_key: str, *args: object, **kwargs: object) -> None:
        values = {
            "mode": "off",
            "group_mpm": 20,
            "output_budget_ratio": 0.8,
            "reserve_mpm": 4,
            "min_session_tick_s": 3.0,
            "active_emitter_window_s": 10.0,
            "active_emitter_ema_alpha": 0.2,
            "rounding_ms": 100,
        }
        field_order = tuple(values)
        if len(args) > len(field_order):
            msg = f"QoSPolicy expected at most {len(field_order) + 1} positional arguments"
            raise TypeError(msg)
        for field_name, field_value in zip(field_order, args, strict=False):
            values[field_name] = field_value
        for field_name, field_value in kwargs.items():
            if field_name not in values:
                raise TypeError(f"QoSPolicy got an unexpected keyword argument '{field_name}'")
            if field_name in field_order[: len(args)]:
                raise TypeError(f"QoSPolicy got multiple values for argument '{field_name}'")
            values[field_name] = field_value

        self.adapter_key = adapter_key
        self.mode = values["mode"]
        self._budget = _QoSBudget(
            group_mpm=values["group_mpm"],
            output_budget_ratio=values["output_budget_ratio"],
            reserve_mpm=values["reserve_mpm"],
        )
        self._cadence = _QoSCadence(
            min_session_tick_s=values["min_session_tick_s"],
            active_emitter_window_s=values["active_emitter_window_s"],
            active_emitter_ema_alpha=values["active_emitter_ema_alpha"],
            rounding_ms=values["rounding_ms"],
        )

    @property
    def group_mpm(self) -> int:
        """Platform group message-per-minute budget."""
        return self._budget.group_mpm

    @property
    def output_budget_ratio(self) -> float:
        """Fraction of group_mpm available for output updates."""
        return self._budget.output_budget_ratio

    @property
    def reserve_mpm(self) -> int:
        """mpm reserved for non-output messages."""
        return self._budget.reserve_mpm

    @property
    def min_session_tick_s(self) -> float:
        """Minimum seconds between dispatches per session."""
        return self._cadence.min_session_tick_s

    @property
    def active_emitter_window_s(self) -> float:
        """Seconds a session remains counted as active after last emit."""
        return self._cadence.active_emitter_window_s

    @property
    def active_emitter_ema_alpha(self) -> float:
        """EMA smoothing factor for active session count."""
        return self._cadence.active_emitter_ema_alpha

    @property
    def rounding_ms(self) -> int:
        """Cadence rounding granularity in milliseconds."""
        return self._cadence.rounding_ms


def telegram_policy(cfg: TelegramQoSConfig) -> QoSPolicy:
    """Build a Telegram QoS policy from config."""
    return QoSPolicy(
        adapter_key="telegram",
        mode="strict" if cfg.enabled else "off",
        group_mpm=cfg.group_mpm,
        output_budget_ratio=cfg.output_budget_ratio,
        reserve_mpm=cfg.reserve_mpm,
        min_session_tick_s=cfg.min_session_tick_s,
        active_emitter_window_s=cfg.active_emitter_window_s,
        active_emitter_ema_alpha=cfg.active_emitter_ema_alpha,
        rounding_ms=cfg.rounding_ms,
    )


def discord_policy(cfg: DiscordQoSConfig) -> QoSPolicy:
    """Build a Discord QoS policy from config.

    Discord starts in coalesce_only mode by default. No hard pacing cap is applied;
    the discord.py library handles transport-level rate limits.
    Document required external limit validation before enabling strict mode.
    """
    return QoSPolicy(
        adapter_key="discord",
        mode=cfg.mode,
        # Discord limits are per-route; use permissive defaults
        group_mpm=50,
        output_budget_ratio=0.9,
        reserve_mpm=5,
        min_session_tick_s=0.1,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.2,
        rounding_ms=100,
    )


def whatsapp_policy(cfg: WhatsAppQoSConfig) -> QoSPolicy:
    """Build a WhatsApp QoS policy from config.

    WhatsApp policy is disabled until adapter-specific throughput limits are
    confirmed via Meta's official documentation and tier agreements.
    Enable only after validating exact constraints for the deployment tier.
    """
    return QoSPolicy(
        adapter_key="whatsapp",
        mode=cfg.mode,
        # Placeholder values; tune after external limit validation
        group_mpm=20,
        output_budget_ratio=0.8,
        reserve_mpm=4,
        min_session_tick_s=3.0,
        active_emitter_window_s=10.0,
        active_emitter_ema_alpha=0.2,
        rounding_ms=100,
    )
