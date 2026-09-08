"""Typed resolution for runtime tunables owned by machine configuration."""

from __future__ import annotations

from teleclaude.config._coerce import as_bool
from teleclaude.config._models import ApiConfig, DaemonConfig, HookOutboxConfig
from teleclaude.config._strictness import SCALAR, ClosedMapping

HOOK_OUTBOX_SECTION = "hook_outbox"
API_SECTION = "api"
DAEMON_SECTION = "daemon"
INVALID_SECTION = "Invalid config key `config.yml:{path}`: expected a mapping."
POLL_INTERVAL_S = "poll_interval_s"
BATCH_SIZE = "batch_size"
LOCK_TTL_S = "lock_ttl_s"
BASE_BACKOFF_S = "base_backoff_s"
MAX_BACKOFF_S = "max_backoff_s"
SESSION_IDLE_TIMEOUT_S = "session_idle_timeout_s"
SESSION_MAX_PENDING = "session_max_pending"
SESSION_CRITICAL_RESERVE = "session_critical_reserve"
SESSION_CLAIM_HIGH_WATERMARK = "session_claim_high_watermark"
SESSION_CLAIM_LOW_WATERMARK = "session_claim_low_watermark"
SUMMARY_INTERVAL_S = "summary_interval_s"
BACKLOG_WARN_THRESHOLD = "backlog_warn_threshold"
LAG_WARN_THRESHOLD_S = "lag_warn_threshold_s"
WARN_LOG_INTERVAL_S = "warn_log_interval_s"
MAX_LAG_SAMPLES = "max_lag_samples"
STALENESS_TTL_S = "staleness_ttl_s"
TCP_PORT = "tcp_port"
WATCH_INTERVAL_S = "watch_interval_s"
WATCH_LAG_THRESHOLD_MS = "watch_lag_threshold_ms"
WATCH_INFLIGHT_THRESHOLD_S = "watch_inflight_threshold_s"
WATCH_DUMP_COOLDOWN_S = "watch_dump_cooldown_s"
MCP_REAPER_INTERVAL_S = "mcp_reaper_interval_s"
WS_CONTROL_SEND_TIMEOUT_S = "ws_control_send_timeout_s"
WS_DEFAULT_SEND_TIMEOUT_S = "ws_default_send_timeout_s"
WS_REPLACEABLE_SEND_TIMEOUT_S = "ws_replaceable_send_timeout_s"
API_RESTART_MAX = "api_restart_max"
API_RESTART_WINDOW_S = "api_restart_window_s"
API_RESTART_BACKOFF_S = "api_restart_backoff_s"
RESOURCE_SNAPSHOT_INTERVAL_S = "resource_snapshot_interval_s"
LAUNCHD_WATCH_INTERVAL_S = "launchd_watch_interval_s"
LAUNCHD_WATCH_ENABLED = "launchd_watch_enabled"
STARTUP_GATE_TIMEOUT_S = "startup_gate_timeout_s"
STARTUP_GATE_POLL_INTERVAL_S = "startup_gate_poll_interval_s"
AGENT_PROMPT_READY_TIMEOUT_S = "agent_prompt_ready_timeout_s"
LOG_LEVEL = "log_level"
LEGACY_GEMINI_ROOT = "legacy_gemini_root"
CLAIM_RESERVE = 8

HOOK_OUTBOX_INPUT = ClosedMapping(
    {
        POLL_INTERVAL_S: SCALAR,
        BATCH_SIZE: SCALAR,
        LOCK_TTL_S: SCALAR,
        BASE_BACKOFF_S: SCALAR,
        MAX_BACKOFF_S: SCALAR,
        SESSION_IDLE_TIMEOUT_S: SCALAR,
        SESSION_MAX_PENDING: SCALAR,
        SESSION_CRITICAL_RESERVE: SCALAR,
        SESSION_CLAIM_HIGH_WATERMARK: SCALAR,
        SESSION_CLAIM_LOW_WATERMARK: SCALAR,
        SUMMARY_INTERVAL_S: SCALAR,
        BACKLOG_WARN_THRESHOLD: SCALAR,
        LAG_WARN_THRESHOLD_S: SCALAR,
        WARN_LOG_INTERVAL_S: SCALAR,
        MAX_LAG_SAMPLES: SCALAR,
        STALENESS_TTL_S: SCALAR,
    }
)
API_INPUT = ClosedMapping(
    {
        TCP_PORT: SCALAR,
        WATCH_INTERVAL_S: SCALAR,
        WATCH_LAG_THRESHOLD_MS: SCALAR,
        WATCH_INFLIGHT_THRESHOLD_S: SCALAR,
        WATCH_DUMP_COOLDOWN_S: SCALAR,
        MCP_REAPER_INTERVAL_S: SCALAR,
        WS_CONTROL_SEND_TIMEOUT_S: SCALAR,
        WS_DEFAULT_SEND_TIMEOUT_S: SCALAR,
        WS_REPLACEABLE_SEND_TIMEOUT_S: SCALAR,
    }
)
DAEMON_INPUT = ClosedMapping(
    {
        API_RESTART_MAX: SCALAR,
        API_RESTART_WINDOW_S: SCALAR,
        API_RESTART_BACKOFF_S: SCALAR,
        RESOURCE_SNAPSHOT_INTERVAL_S: SCALAR,
        LAUNCHD_WATCH_INTERVAL_S: SCALAR,
        LAUNCHD_WATCH_ENABLED: SCALAR,
        STARTUP_GATE_TIMEOUT_S: SCALAR,
        STARTUP_GATE_POLL_INTERVAL_S: SCALAR,
        AGENT_PROMPT_READY_TIMEOUT_S: SCALAR,
        LOG_LEVEL: SCALAR,
        LEGACY_GEMINI_ROOT: SCALAR,
    }
)


def _section(raw: object, path: str) -> dict[str, object]:  # guard: loose-dict - merged YAML config section
    """Return a required merged configuration section as a mapping."""
    if not isinstance(raw, dict):
        raise ValueError(INVALID_SECTION.format(path=path))
    return raw


def _int(value: object) -> int:
    """Parse an integer machine-config scalar without accepting booleans."""
    if isinstance(value, bool):
        raise ValueError(str(value))
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise ValueError(str(value))


def _float(value: object) -> float:
    """Parse a numeric machine-config scalar without accepting booleans."""
    if isinstance(value, bool):
        raise ValueError(str(value))
    if isinstance(value, (int, float, str)):
        return float(value)
    raise ValueError(str(value))


def parse_hook_outbox_config(raw: object) -> HookOutboxConfig:
    """Resolve hook-outbox tunables and enforce their queue relationships."""
    section = _section(raw, HOOK_OUTBOX_SECTION)
    max_pending = _int(section[SESSION_MAX_PENDING])
    high = _int(section.get(SESSION_CLAIM_HIGH_WATERMARK, max(1, max_pending - CLAIM_RESERVE)))
    low = _int(section.get(SESSION_CLAIM_LOW_WATERMARK, max(0, high // 3)))
    high = min(high, max_pending)
    if low >= high:
        low = max(0, high - 1)
    reserve = min(max(_int(section[SESSION_CRITICAL_RESERVE]), 0), max_pending)
    return HookOutboxConfig(
        poll_interval_s=_float(section[POLL_INTERVAL_S]),
        batch_size=_int(section[BATCH_SIZE]),
        lock_ttl_s=_float(section[LOCK_TTL_S]),
        base_backoff_s=_float(section[BASE_BACKOFF_S]),
        max_backoff_s=_float(section[MAX_BACKOFF_S]),
        session_idle_timeout_s=_float(section[SESSION_IDLE_TIMEOUT_S]),
        session_max_pending=max_pending,
        session_critical_reserve=reserve,
        session_claim_high_watermark=high,
        session_claim_low_watermark=low,
        summary_interval_s=_float(section[SUMMARY_INTERVAL_S]),
        backlog_warn_threshold=_int(section[BACKLOG_WARN_THRESHOLD]),
        lag_warn_threshold_s=_float(section[LAG_WARN_THRESHOLD_S]),
        warn_log_interval_s=_float(section[WARN_LOG_INTERVAL_S]),
        max_lag_samples=_int(section[MAX_LAG_SAMPLES]),
        staleness_ttl_s=_float(section[STALENESS_TTL_S]),
    )


def parse_api_config(raw: object) -> ApiConfig:
    """Resolve API transport and monitoring tunables."""
    section = _section(raw, API_SECTION)
    return ApiConfig(
        tcp_port=_int(section[TCP_PORT]),
        watch_interval_s=_float(section[WATCH_INTERVAL_S]),
        watch_lag_threshold_ms=_float(section[WATCH_LAG_THRESHOLD_MS]),
        watch_inflight_threshold_s=_float(section[WATCH_INFLIGHT_THRESHOLD_S]),
        watch_dump_cooldown_s=_float(section[WATCH_DUMP_COOLDOWN_S]),
        mcp_reaper_interval_s=_float(section[MCP_REAPER_INTERVAL_S]),
        ws_control_send_timeout_s=_float(section[WS_CONTROL_SEND_TIMEOUT_S]),
        ws_default_send_timeout_s=_float(section[WS_DEFAULT_SEND_TIMEOUT_S]),
        ws_replaceable_send_timeout_s=_float(section[WS_REPLACEABLE_SEND_TIMEOUT_S]),
    )


def parse_daemon_config(raw: object) -> DaemonConfig:
    """Resolve daemon tunables for runtime construction and operator reflection."""
    section = _section(raw, DAEMON_SECTION)
    return DaemonConfig(
        api_restart_max=_int(section[API_RESTART_MAX]),
        api_restart_window_s=_float(section[API_RESTART_WINDOW_S]),
        api_restart_backoff_s=_float(section[API_RESTART_BACKOFF_S]),
        resource_snapshot_interval_s=_float(section[RESOURCE_SNAPSHOT_INTERVAL_S]),
        launchd_watch_interval_s=_float(section[LAUNCHD_WATCH_INTERVAL_S]),
        launchd_watch_enabled=as_bool(section[LAUNCHD_WATCH_ENABLED]),
        startup_gate_timeout_s=_float(section[STARTUP_GATE_TIMEOUT_S]),
        startup_gate_poll_interval_s=_float(section[STARTUP_GATE_POLL_INTERVAL_S]),
        agent_prompt_ready_timeout_s=_float(section[AGENT_PROMPT_READY_TIMEOUT_S]),
        log_level=str(section[LOG_LEVEL]),
        legacy_gemini_root=str(section[LEGACY_GEMINI_ROOT]),
    )
