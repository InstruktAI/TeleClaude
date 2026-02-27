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


@dataclass
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

    adapter_key: str
    mode: str = "off"  # "off" | "coalesce_only" | "strict"
    group_mpm: int = 20
    output_budget_ratio: float = 0.8
    reserve_mpm: int = 4
    min_session_tick_s: float = 3.0
    active_emitter_window_s: float = 10.0
    active_emitter_ema_alpha: float = 0.2
    rounding_ms: int = 100


def telegram_policy(cfg: "TelegramQoSConfig") -> QoSPolicy:
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


def discord_policy(cfg: "DiscordQoSConfig") -> QoSPolicy:
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


def whatsapp_policy(cfg: "WhatsAppQoSConfig") -> QoSPolicy:
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
