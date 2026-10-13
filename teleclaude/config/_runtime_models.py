"""Closed runtime-tunable configuration models."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Self

from pydantic import Field, TypeAdapter, ValidationInfo, field_validator, model_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.config._coerce import FLAG, FLOAT_STRICT, INT_STRICT, TEXT
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.config.tiers import Tier

_INVALID_SECTION_TEMPLATE = "Invalid config key `config.yml:{section}`: expected a mapping."
_JANITOR_INTEGER_ERROR = "process_janitor.{field} must be an integer"
_JANITOR_MINIMUM_ERROR = "process_janitor.{field} must be greater than or equal to 60"
_WORKFLOW_RUNNER_ERROR = "workflow.runner must be one of {members}"
_WORKFLOW_DISPATCH_MINIMUM_ERROR = "workflow.max_todo_dispatch must be greater than or equal to 1"
_WORKFLOW_DISPATCH_INTEGER_ERROR = "workflow.max_todo_dispatch must be an integer"
_DEPLOYMENT_CHANNEL_ERROR = "deployment.channel must be one of {channels}"
_DEPLOYMENT_STABLE_ERROR = "deployment.compatibility_series is required and must be non-empty when channel=stable"
_WORKFLOW_AUTOSTART_SECTION = "workflow.autostart"
_EMPTY_TEXT = ""
_TERMINAL_MAPPING_ERROR = "Invalid config key `config.yml:terminal`: expected a mapping."
_HOOK_OUTBOX_SECTION = "hook_outbox"
_API_SECTION = "api"
_DAEMON_SECTION = "daemon"
_PROCESS_JANITOR_SECTION = "process_janitor"
_WORKFLOW_SECTION = "workflow"
_DEPLOYMENT_SECTION = "deployment"
_DEPLOYMENT_CHANNEL_FIELD = "channel"


class _HookOutboxField(StrEnum):
    """Input keys used while deriving hook-outbox queue watermarks."""

    SESSION_MAX_PENDING = "session_max_pending"
    SESSION_CLAIM_HIGH_WATERMARK = "session_claim_high_watermark"
    SESSION_CLAIM_LOW_WATERMARK = "session_claim_low_watermark"


def _require_mapping(value: object, message: str) -> object:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _required_section(value: object, section: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(_INVALID_SECTION_TEMPLATE.format(section=section))
    return value


class HookOutboxConfig(ClosedModel):
    """Resolved hook-outbox delivery and queue limits."""

    poll_interval_s: FLOAT_STRICT
    batch_size: INT_STRICT
    lock_ttl_s: FLOAT_STRICT
    base_backoff_s: FLOAT_STRICT
    max_backoff_s: FLOAT_STRICT
    session_idle_timeout_s: FLOAT_STRICT
    session_max_pending: INT_STRICT
    session_critical_reserve: INT_STRICT
    session_claim_high_watermark: INT_STRICT
    session_claim_low_watermark: INT_STRICT
    summary_interval_s: FLOAT_STRICT
    backlog_warn_threshold: INT_STRICT
    lag_warn_threshold_s: FLOAT_STRICT
    warn_log_interval_s: FLOAT_STRICT
    max_lag_samples: INT_STRICT
    staleness_ttl_s: FLOAT_STRICT

    @model_validator(mode="before")
    @classmethod
    def _derive_queue_watermarks(cls, value: object) -> object:
        section = _required_section(value, _HOOK_OUTBOX_SECTION)
        result = dict(section)
        max_pending = TypeAdapter(INT_STRICT).validate_python(result[_HookOutboxField.SESSION_MAX_PENDING])
        high = (
            TypeAdapter(INT_STRICT).validate_python(result[_HookOutboxField.SESSION_CLAIM_HIGH_WATERMARK])
            if _HookOutboxField.SESSION_CLAIM_HIGH_WATERMARK in result
            else max(1, max_pending - 8)
        )
        result[_HookOutboxField.SESSION_CLAIM_HIGH_WATERMARK] = high
        result[_HookOutboxField.SESSION_CLAIM_LOW_WATERMARK] = (
            TypeAdapter(INT_STRICT).validate_python(result[_HookOutboxField.SESSION_CLAIM_LOW_WATERMARK])
            if _HookOutboxField.SESSION_CLAIM_LOW_WATERMARK in result
            else max(0, high // 3)
        )
        return result

    @model_validator(mode="after")
    def _clamp_queue_watermarks(self) -> Self:
        self.session_claim_high_watermark = min(self.session_claim_high_watermark, self.session_max_pending)
        if self.session_claim_low_watermark >= self.session_claim_high_watermark:
            self.session_claim_low_watermark = max(0, self.session_claim_high_watermark - 1)
        self.session_critical_reserve = min(max(self.session_critical_reserve, 0), self.session_max_pending)
        return self


class ApiConfig(ClosedModel):
    """Resolved API transport and monitoring tunables."""

    tcp_port: INT_STRICT = Field(json_schema_extra={"tier": Tier.PUBLIC})
    watch_interval_s: FLOAT_STRICT
    watch_lag_threshold_ms: FLOAT_STRICT
    watch_inflight_threshold_s: FLOAT_STRICT
    watch_dump_cooldown_s: FLOAT_STRICT
    mcp_reaper_interval_s: FLOAT_STRICT
    ws_control_send_timeout_s: FLOAT_STRICT
    ws_default_send_timeout_s: FLOAT_STRICT
    ws_replaceable_send_timeout_s: FLOAT_STRICT

    @model_validator(mode="before")
    @classmethod
    def _require_api_mapping(cls, value: object) -> object:
        return _required_section(value, _API_SECTION)


class DaemonConfig(ClosedModel):
    """Daemon lifecycle, monitoring, and logging configuration."""

    api_restart_max: INT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    api_restart_window_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    api_restart_backoff_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    resource_snapshot_interval_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    launchd_watch_interval_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    launchd_watch_enabled: FLAG = Field(json_schema_extra={"tier": Tier.INTERNAL})
    startup_gate_timeout_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    startup_gate_poll_interval_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    agent_prompt_ready_timeout_s: FLOAT_STRICT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    log_level: TEXT = Field(json_schema_extra={"tier": Tier.TUI})
    legacy_gemini_root: TEXT = Field(json_schema_extra={"tier": Tier.INTERNAL})

    @model_validator(mode="before")
    @classmethod
    def _require_daemon_mapping(cls, value: object) -> object:
        return _required_section(value, _DAEMON_SECTION)


class ProcessJanitorConfig(ClosedModel):
    """Process janitor timing and safety defaults."""

    scan_interval_seconds: INT_STRICT = 300
    default_signature_ttl_seconds: INT_STRICT = 3600
    lease_ttl_seconds: INT_STRICT = 1800
    dry_run_default: FLAG = True
    reap_revalidation_seconds: INT_STRICT = 3600

    @field_validator(
        "scan_interval_seconds",
        "default_signature_ttl_seconds",
        "lease_ttl_seconds",
        "reap_revalidation_seconds",
        mode="before",
    )
    @classmethod
    def _parse_duration(cls, value: object, info: ValidationInfo) -> object:
        field_name = info.field_name
        if field_name is None:
            return value
        if value is None:
            return cls.model_fields[field_name].default
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str) and value.strip().isdigit():
            parsed = int(value.strip())
        else:
            raise ValueError(_JANITOR_INTEGER_ERROR.format(field=field_name))
        if parsed < 60:
            raise ValueError(_JANITOR_MINIMUM_ERROR.format(field=field_name))
        return parsed

    @model_validator(mode="before")
    @classmethod
    def _default_missing_section(cls, value: object) -> object:
        return {} if value is None else _required_section(value, _PROCESS_JANITOR_SECTION)


class WorkflowAutostartConfig(ClosedModel):
    """Per-kind automatic lifecycle-runner dispatch policy (off by default)."""

    feature: FLAG = False
    change: FLAG = False
    bug: FLAG = False
    task: FLAG = False

    @model_validator(mode="before")
    @classmethod
    def _default_missing_autostart(cls, value: object) -> object:
        return (
            {}
            if value is None
            else _require_mapping(value, _INVALID_SECTION_TEMPLATE.format(section=_WORKFLOW_AUTOSTART_SECTION))
        )


class WorkflowRunnerMode(StrEnum):
    """Master switch over the lifecycle runner's autonomous dispatch path."""

    AUTOSTART = "autostart"
    MANUAL = "manual"


class WorkflowConfig(ClosedModel):
    """Daemon-runtime lifecycle-runner control plane."""

    autostart: WorkflowAutostartConfig = Field(
        default_factory=WorkflowAutostartConfig, json_schema_extra={"tier": Tier.PUBLIC}
    )
    runner: WorkflowRunnerMode = Field(default=WorkflowRunnerMode.AUTOSTART, json_schema_extra={"tier": Tier.PUBLIC})
    max_todo_dispatch: int = Field(default=5, json_schema_extra={"tier": Tier.PUBLIC})

    @model_validator(mode="before")
    @classmethod
    def _default_missing_workflow_section(cls, value: object) -> object:
        return {} if value is None else _required_section(value, _WORKFLOW_SECTION)

    @field_validator("runner", mode="before")
    @classmethod
    def _validate_runner(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError(_WORKFLOW_RUNNER_ERROR.format(members=[mode.value for mode in WorkflowRunnerMode]))
        try:
            return WorkflowRunnerMode(value)
        except ValueError:
            raise ValueError(
                _WORKFLOW_RUNNER_ERROR.format(members=[mode.value for mode in WorkflowRunnerMode])
            ) from None

    @field_validator("max_todo_dispatch", mode="before")
    @classmethod
    def _parse_positive_dispatch_limit(cls, value: object) -> int:
        if isinstance(value, bool):
            raise ValueError(_WORKFLOW_DISPATCH_INTEGER_ERROR)
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str) and value.strip().isdigit():
            parsed = int(value.strip())
        else:
            raise ValueError(_WORKFLOW_DISPATCH_INTEGER_ERROR)
        if parsed < 1:
            raise ValueError(_WORKFLOW_DISPATCH_MINIMUM_ERROR)
        return parsed


class ReleaseChannel(StrEnum):
    """TeleClaude self-update release channel."""

    ALPHA = "alpha"
    BETA = "beta"
    STABLE = "stable"


class DeploymentConfig(ClosedModel):
    """Release channel and compatibility series for TeleClaude self-update.

    Machine-wide: the release channel governs this host's self-update — installed
    once per host, not per project. ``stable`` requires a ``compatibility_series``: the
    minor line while the major is zero, the major line once it is positive. Alpha and
    beta never read it, so a value carried there is accepted unvalidated.
    """

    channel: ReleaseChannel = ReleaseChannel.ALPHA
    compatibility_series: TEXT = ""

    @model_validator(mode="before")
    @classmethod
    def _default_missing_deployment_section(cls, value: object) -> object:
        return {} if value is None else _required_section(value, _DEPLOYMENT_SECTION)

    @field_validator("channel", mode="before")
    @classmethod
    def _parse_release_channel(cls, value: object) -> ReleaseChannel:
        try:
            return ReleaseChannel(str(value))
        except ValueError:
            channels = [channel.value for channel in ReleaseChannel]
            raise ValueError(_DEPLOYMENT_CHANNEL_ERROR.format(channels=channels)) from None

    @field_validator("compatibility_series", mode="before")
    @classmethod
    def _canonicalize_series(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return _EMPTY_TEXT
        if info.data.get(_DEPLOYMENT_CHANNEL_FIELD) is not ReleaseChannel.STABLE or value == _EMPTY_TEXT:
            return value
        return str(CompatibilitySeries.parse(value))

    @model_validator(mode="after")
    def _validate_stable_series(self) -> Self:
        if self.channel == ReleaseChannel.STABLE and not self.compatibility_series:
            raise ValueError(_DEPLOYMENT_STABLE_ERROR)
        return self

    @property
    def series(self) -> CompatibilitySeries | None:
        """The series stable self-update follows; None on a channel that follows none."""
        return CompatibilitySeries.parse(self.compatibility_series) if self.channel == ReleaseChannel.STABLE else None


class TerminalConfig(ClosedModel):
    """Terminal display settings."""

    strip_ansi: FLAG = True

    @model_validator(mode="before")
    @classmethod
    def _require_terminal_mapping(cls, value: object) -> object:
        return _require_mapping(value, _TERMINAL_MAPPING_ERROR)
