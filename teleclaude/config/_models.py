"""Closed Pydantic models for the machine runtime configuration.

The typed shapes the application reads configuration through. Parsing from raw
YAML/.env into these models lives at the machine-config loading boundary; these
are the schema definitions only.

Editability is opt-in and code-led: every field carries a ``tier`` in its
``metadata`` — ``internal`` (the default), ``public``, or ``tui`` — declaring what
reaches humans. A field with no marker is ``internal``: absent from the generated
``templates/config.yml`` sample, absent from the config TUI, not human-editable.
``public`` fields are the ``config.yml`` surface (in the generated sample);
``tui`` fields are the operator-facing subset the wizard renders. A container
field's tier is inherited by its unmarked nested leaves. The field tiers are the
single authority for what is public — the defaults blob and the sample follow
from them. See ``local/projects/teleclaude/policy/config-public-surface``.

A container whose members are themselves structured is not a leaf: its members
carry their own tiers, so a schema walk that treats the container as opaque lets
those tiers claim a surface nothing enforces. Such a field is therefore either
governed member-by-member or carries ``ungoverned_body`` in its metadata stating
why it is not; an unmarked one raises, and the reason must be a non-empty string
rather than a bare flag. The marker is a declaration, not a dispensation — it
records that membership is authored in the config file rather than declared by
the schema, so there is no static leaf for the walk to address. A closed
vocabulary modelled as an open map does not qualify: it states the gap plainly
and is keyed by its enum instead.
"""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from enum import StrEnum
from typing import Annotated, NamedTuple, Protocol, Self, cast

from pydantic import (
    Field,
    ModelWrapValidatorHandler,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from teleclaude.agent_registry import AgentName
from teleclaude.closed_model import SENSITIVE, ClosedModel
from teleclaude.config._chiptunes import ChiptunesConfig
from teleclaude.config._coerce import (
    FLAG,
    INT_LENIENT,
    OPT_INT_LENIENT,
    OPT_TEXT,
    SCALAR_INPUT,
    TEXT,
    TRUTHY_TEXT,
)
from teleclaude.config._remote_computers import RemoteComputerConfig
from teleclaude.config._runtime_models import (
    ApiConfig as ApiConfig,
)
from teleclaude.config._runtime_models import (
    DaemonConfig as DaemonConfig,
)
from teleclaude.config._runtime_models import (
    DeploymentConfig as DeploymentConfig,
)
from teleclaude.config._runtime_models import (
    HookOutboxConfig as HookOutboxConfig,
)
from teleclaude.config._runtime_models import (
    ProcessJanitorConfig as ProcessJanitorConfig,
)
from teleclaude.config._runtime_models import (
    ReleaseChannel as ReleaseChannel,
)
from teleclaude.config._runtime_models import (
    TerminalConfig as TerminalConfig,
)
from teleclaude.config._runtime_models import (
    WorkflowAutostartConfig as WorkflowAutostartConfig,
)
from teleclaude.config._runtime_models import (
    WorkflowConfig as WorkflowConfig,
)
from teleclaude.config._runtime_models import (
    WorkflowRunnerMode as WorkflowRunnerMode,
)
from teleclaude.config._schema_paths import PATH_SEPARATOR, master_scoped_paths, resolve_schema_scope
from teleclaude.config._summarizer import SummarizerConfig
from teleclaude.config.effective_enabled import settle_effective_enabled
from teleclaude.config.tiers import GOVERNS_SECTION_METADATA_KEY, SCOPE_METADATA_KEY, Scope, Tier
from teleclaude.config.validation import AvailabilityAnswer, configuration_availability


class ConfigValidationIssue(NamedTuple):
    loc: tuple[str | int, ...]
    message: str
    input: object
    code: str = "value_error"


class AggregateInputDerivation(Protocol):
    def prepare(self, data: object) -> tuple[object, list[ConfigValidationIssue]]: ...


_COMPUTER_MAPPING_ERROR = "Invalid config key `config.yml:computer`: expected a mapping."
_REDIS_MAPPING_ERROR = "Invalid config key `config.yml:redis`: expected a mapping."
_REDIS_LOCAL_MAPPING_ERROR = "Invalid config key `config.yml:redis.local`: expected a mapping."
_UNIX_SOCKET_SCHEME = "unix://"
_REDIS_LOCAL_SOCKET_ERROR = (
    "Invalid config key `config.yml:redis.local.url`: the local Redis is reached over a unix:// socket only."
)
_REDIS_CLUSTER_MAPPING_ERROR = "Invalid config key `config.yml:redis.cluster`: expected a mapping."
_HOOK_OUTBOX_MAPPING_ERROR = "Invalid config key `config.yml:hook_outbox`: expected a mapping."
_API_MAPPING_ERROR = "Invalid config key `config.yml:api`: expected a mapping."
_DAEMON_MAPPING_ERROR = "Invalid config key `config.yml:daemon`: expected a mapping."
_TERMINAL_MAPPING_ERROR = "Invalid config key `config.yml:terminal`: expected a mapping."
_TELEGRAM_MAPPING_ERROR = "Invalid config key `config.yml:telegram`: expected a mapping."
_DISCORD_MAPPING_ERROR = "Invalid config key `config.yml:discord`: expected a mapping."
_WHATSAPP_MAPPING_ERROR = "Invalid config key `config.yml:whatsapp`: expected a mapping."
_EMAIL_MAPPING_ERROR = "Invalid config key `config.yml:email`: expected a mapping."
_MISSING_PROFILE_TEMPLATE = "Agent `{binary}` declares no launch profile `{profile}`."
_BACKUP_MAPPING_ERROR = "Invalid config key `config.yml:backup`: expected a mapping."
_TTS_DISCORD_VOICE_ERROR = "tts.services.{service}.discord_voice '{voice}' is not in this service's voices"
_TTS_DEFAULT_INSTRUCT = "A clear, natural conversational voice."
_PYDANTIC_VALUE_ERROR = "value_error"
_EXPERIMENT_DIMENSION_ERROR = "Experiment dimensions must be iterable configuration values."
_EMPTY_TEXT = ""
_EN_US_TEXT = "en_US"


class TTSProvider(StrEnum):
    """Providers with a specialized configuration contract."""

    VOXCPM = "voxcpm"


class _ValidationDetail(StrEnum):
    TYPE = "type"
    LOC = "loc"
    INPUT = "input"
    CTX = "ctx"


class _ConfigKey(StrEnum):
    EVENTS = "events"
    MESSAGE = "message"
    MESSAGES = "messages"
    SERVICES = "services"
    SERVICE_PRIORITY = "service_priority"
    VOICES = "voices"
    PARAMS = "params"
    NAME = "name"
    VOICE_ID = "voice_id"
    ENABLED = "enabled"
    MODEL = "model"
    API_KEY = "api_key"
    CLI_BIN = "cli_bin"
    INSTRUCT = "instruct"
    DISCORD_VOICE = "discord_voice"
    QOS = "qos"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    PHONE_NUMBER = "phone_number"
    TEMPLATE_LANGUAGE = "template_language"


def _require_mapping(value: object, message: str) -> object:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return value


def _mapping_or_empty(value: object, message: str) -> object:
    if value is None:
        return {}
    return _require_mapping(value, message)


def _scalar_text_or_raw(value: object) -> object:
    if isinstance(value, (Mapping, list)):
        return value
    return str(value)


def _normalize_tts_voice(value: Mapping[object, object], service_name: object) -> dict[object, object]:
    """Preserve parameter overrides only for the provider that owns them."""
    voice = dict(value)
    if service_name != TTSProvider.VOXCPM:
        voice.pop(_ConfigKey.PARAMS, None)
    voice[_ConfigKey.NAME] = _scalar_text_or_raw(voice.get(_ConfigKey.NAME, _EMPTY_TEXT))
    raw_voice_id = voice.get(_ConfigKey.VOICE_ID)
    voice[_ConfigKey.VOICE_ID] = _scalar_text_or_raw(raw_voice_id) if raw_voice_id else None
    return voice


def _normalize_tts_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    data = dict(value)
    data.setdefault(_ConfigKey.ENABLED, False)
    data.setdefault(_ConfigKey.SERVICE_PRIORITY, [])
    priority = data.get(_ConfigKey.SERVICE_PRIORITY, [])
    if isinstance(priority, list):
        data[_ConfigKey.SERVICE_PRIORITY] = [_scalar_text_or_raw(item) for item in priority]
    raw_events = data.get(_ConfigKey.EVENTS)
    if raw_events is None:
        data[_ConfigKey.EVENTS] = {}
    elif isinstance(raw_events, Mapping):
        events: dict[object, object] = {}
        for event_name, event_value in raw_events.items():
            if not isinstance(event_value, Mapping):
                events[event_name] = event_value
                continue
            event = dict(event_value)
            event.setdefault(_ConfigKey.ENABLED, False)
            legacy = event.get(_ConfigKey.MESSAGE)
            raw_messages = event.get(_ConfigKey.MESSAGES)
            messages = (
                [_scalar_text_or_raw(item) for item in raw_messages if item] if isinstance(raw_messages, list) else []
            )
            invalid_legacy = isinstance(legacy, (Mapping, list))
            if invalid_legacy:
                event[_ConfigKey.MESSAGE] = legacy
            else:
                event.pop(_ConfigKey.MESSAGE, None)
                if not messages and legacy:
                    messages = [_scalar_text_or_raw(legacy)]
            event[_ConfigKey.MESSAGES] = messages or None
            events[event_name] = event
        data[_ConfigKey.EVENTS] = events
    raw_services = data.get(_ConfigKey.SERVICES)
    if raw_services is None:
        data[_ConfigKey.SERVICES] = {}
    elif isinstance(raw_services, Mapping):
        services: dict[object, object] = {}
        for service_name, service_value in raw_services.items():
            if not isinstance(service_value, Mapping):
                services[service_name] = service_value
                continue
            service = dict(service_value)
            service.setdefault(_ConfigKey.ENABLED, False)
            raw_voices = service.get(_ConfigKey.VOICES, [])
            if isinstance(raw_voices, list):
                voices: list[object] = []
                for voice_value in raw_voices:
                    if not isinstance(voice_value, Mapping):
                        voices.append(voice_value)
                        continue
                    voice = _normalize_tts_voice(voice_value, service_name)
                    voices.append(voice)
                service[_ConfigKey.VOICES] = voices or None
            raw_params = service.get(_ConfigKey.PARAMS)
            service[_ConfigKey.PARAMS] = dict(raw_params) if isinstance(raw_params, Mapping) else None
            raw_instruct = service.get(_ConfigKey.INSTRUCT, _TTS_DEFAULT_INSTRUCT)
            service[_ConfigKey.INSTRUCT] = _scalar_text_or_raw(raw_instruct or _TTS_DEFAULT_INSTRUCT)
            voice_names: list[str] = [
                voice[_ConfigKey.NAME]
                for voice in service.get(_ConfigKey.VOICES, []) or []
                if isinstance(voice, Mapping) and isinstance(voice.get(_ConfigKey.NAME), str)
            ]
            declared_voice = service.get(_ConfigKey.DISCORD_VOICE)
            if not voice_names:
                if not isinstance(declared_voice, (Mapping, list)):
                    service[_ConfigKey.DISCORD_VOICE] = None
            elif not isinstance(declared_voice, (Mapping, list)):
                normalized_voice: str | None = TypeAdapter(OPT_TEXT).validate_python(declared_voice)
                resolved_voice = normalized_voice or voice_names[0]
                if resolved_voice not in voice_names:
                    detail = InitErrorDetails(
                        type=PydanticCustomError(
                            _PYDANTIC_VALUE_ERROR,
                            _TTS_DISCORD_VOICE_ERROR.format(service=service_name, voice=resolved_voice),  # pyright: ignore[reportArgumentType] - custom diagnostic text is dynamic
                        ),
                        loc=(_ConfigKey.SERVICES, service_name, _ConfigKey.DISCORD_VOICE),
                        input=declared_voice,
                    )
                    raise ValidationError.from_exception_data(
                        TTSConfig.__name__,
                        [detail],
                    )
                service[_ConfigKey.DISCORD_VOICE] = resolved_voice
            services[service_name] = service
        data[_ConfigKey.SERVICES] = services
    return data


def _normalize_stt_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    data = dict(value)
    data.setdefault(_ConfigKey.ENABLED, False)
    data.setdefault(_ConfigKey.SERVICE_PRIORITY, [])
    priority = data.get(_ConfigKey.SERVICE_PRIORITY, [])
    if isinstance(priority, list):
        data[_ConfigKey.SERVICE_PRIORITY] = [_scalar_text_or_raw(item) for item in priority]
    raw_services = data.get(_ConfigKey.SERVICES)
    if raw_services is None:
        data[_ConfigKey.SERVICES] = {}
    elif isinstance(raw_services, Mapping):
        services: dict[object, object] = {}
        for service_name, service_value in raw_services.items():
            if isinstance(service_value, Mapping):
                service = dict(service_value)
                service.setdefault(_ConfigKey.ENABLED, False)
                services[service_name] = service
            else:
                services[service_name] = service_value
        data[_ConfigKey.SERVICES] = services
    return data


class PollingConfig(ClosedModel):
    """Agent output polling intervals."""

    directory_check_interval: int
    output_cadence_s: float = 1.0


class ComputerConfig(ClosedModel):
    name: TEXT = Field(json_schema_extra={"tier": Tier.TUI})
    user: TEXT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    role: TEXT = Field(json_schema_extra={"tier": Tier.TUI})
    timezone: TEXT = Field(json_schema_extra={"tier": Tier.TUI})
    default_working_dir: TEXT = Field(json_schema_extra={"tier": Tier.INTERNAL})
    is_master: FLAG = Field(json_schema_extra={"tier": Tier.TUI})
    # Optional LAN address override; auto-detected when unset.
    host: TEXT | None = Field(default=None, json_schema_extra={"tier": Tier.TUI})
    tmux_binary: TEXT = Field(default="tmux", json_schema_extra={"tier": Tier.INTERNAL})
    is_ingress_node: FLAG = Field(default=False, json_schema_extra={"tier": Tier.TUI})

    @model_validator(mode="before")
    @classmethod
    def _validate_computer_mapping(cls, value: object) -> object:
        return _require_mapping(value, _COMPUTER_MAPPING_ERROR)


class ModelChainEntry(ClosedModel):
    """One declared launch-model fallback entry: model label, opaque launch
    flags, and an optional per-launch patch parameter map (JSON of loader-id
    -> config) rendered into the session's ephemeral --patch overlay."""

    model: str
    flags: str
    patch: str = ""


class AgentConfig(ClosedModel):
    """Configuration for a specific AI agent."""

    binary: str = Field(json_schema_extra={"tier": Tier.INTERNAL})  # Resolved by runtime policy
    profiles: dict[str, str] = Field(json_schema_extra={"tier": Tier.PUBLIC})
    session_dir: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    log_pattern: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    mode_chains: dict[str, list[ModelChainEntry]] = Field(json_schema_extra={"tier": Tier.INTERNAL})
    model_chains: dict[str, list[ModelChainEntry]] = Field(json_schema_extra={"tier": Tier.PUBLIC})
    exec_subcommand: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    # Flag to add before prompt for interactive mode (e.g., "-i")
    interactive_flag: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    # Flag for non-interactive/pipe mode (e.g., "-p")
    non_interactive_flag: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    resume_template: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    continue_template: str = Field(default="", json_schema_extra={"tier": Tier.INTERNAL})
    prompt_at_launch: bool = Field(default=False, json_schema_extra={"tier": Tier.INTERNAL})
    model_via_launch_patch: bool = Field(default=False, json_schema_extra={"tier": Tier.INTERNAL})
    restricted_sandbox_mode: str = Field(default="", json_schema_extra={"tier": Tier.INTERNAL})
    enabled: bool = Field(default=True, json_schema_extra={"tier": Tier.TUI})
    # git --author value; from constants.GIT_AUTHOR_IDENTITIES at load time
    git_identity: str | None = Field(default=None, json_schema_extra={"tier": Tier.INTERNAL})

    def get_command(self, profile: str = "default") -> str:
        """Assembled base command: binary + profile flags."""
        flags = self.profiles.get(profile)
        if flags is None:
            raise ValueError(_MISSING_PROFILE_TEMPLATE.format(binary=self.binary, profile=profile))
        return f"{self.binary} {flags}".strip()

    @property
    def command(self) -> str:
        """Assembled base command: binary + default flags."""
        return self.get_command("default")


class LocalRedisConfig(ClosedModel):
    """This computer's own Redis for local events, reached over a Unix socket only; unset, local events use cluster."""

    url: Annotated[TRUTHY_TEXT, SENSITIVE]
    username: Annotated[TRUTHY_TEXT, SENSITIVE]
    password: Annotated[TRUTHY_TEXT, SENSITIVE]
    max_connections: INT_LENIENT
    socket_timeout: INT_LENIENT

    @model_validator(mode="before")
    @classmethod
    def _validate_redis_mapping(cls, value: object) -> object:
        return _require_mapping(value, _REDIS_LOCAL_MAPPING_ERROR)

    @model_validator(mode="after")
    def _require_unix_socket(self) -> Self:
        if self.url is not None and not self.url.startswith(_UNIX_SOCKET_SCHEME):
            raise ValueError(_REDIS_LOCAL_SOCKET_ERROR)
        return self


class ClusterRedisConfig(ClosedModel):
    """The shared Redis for cluster events and the cross-computer transport."""

    url: Annotated[TEXT, SENSITIVE]
    password: Annotated[TRUTHY_TEXT, SENSITIVE]
    max_connections: INT_LENIENT
    socket_timeout: INT_LENIENT
    message_stream_maxlen: INT_LENIENT
    output_stream_maxlen: INT_LENIENT
    output_stream_ttl: INT_LENIENT

    @model_validator(mode="before")
    @classmethod
    def _validate_redis_mapping(cls, value: object) -> object:
        return _require_mapping(value, _REDIS_CLUSTER_MAPPING_ERROR)


class RedisConfig(ClosedModel):
    """One Redis per event scope: this computer's local Redis and the shared cluster Redis."""

    local: LocalRedisConfig
    cluster: ClusterRedisConfig

    @model_validator(mode="before")
    @classmethod
    def _validate_redis_mapping(cls, value: object) -> object:
        return _require_mapping(value, _REDIS_MAPPING_ERROR)


class EventReliabilityConfig(ClosedModel):
    """Event processor reliability controls."""

    idle_threshold_ms: int
    max_attempts: int
    sweep_interval_ms: int
    dlq_destination: str


AGENT_NO_START_TIMEOUT_S = 90
AGENT_NO_SIGNAL_TIMEOUT_S = 300


class TelegramQoSConfig(ClosedModel):
    """QoS configuration for Telegram output pacing and coalescing."""

    enabled: bool = True
    group_mpm: int = 20
    output_budget_ratio: float = 0.8
    reserve_mpm: int = 4
    min_session_tick_s: float = 3.0
    active_emitter_window_s: float = 10.0
    active_emitter_ema_alpha: float = 0.2
    rounding_ms: int = 100


class _TelegramQoSInput(ClosedModel):
    enabled: SCALAR_INPUT = None
    group_mpm: SCALAR_INPUT = None
    output_budget_ratio: SCALAR_INPUT = None
    reserve_mpm: SCALAR_INPUT = None
    min_session_tick_s: SCALAR_INPUT = None
    active_emitter_window_s: SCALAR_INPUT = None
    active_emitter_ema_alpha: SCALAR_INPUT = None
    rounding_ms: SCALAR_INPUT = None


class TelegramConfig(ClosedModel):
    """Telegram adapter configuration."""

    enabled: FLAG = False
    bot_token: Annotated[OPT_TEXT, SENSITIVE] = None
    qos: TelegramQoSConfig = Field(default_factory=TelegramQoSConfig, json_schema_extra={"tier": Tier.INTERNAL})

    @model_validator(mode="before")
    @classmethod
    def _mapping_or_default(cls, value: object) -> object:
        mapped = _mapping_or_empty(value, _TELEGRAM_MAPPING_ERROR)
        if not isinstance(mapped, Mapping):
            return mapped
        data = dict(mapped)
        qos = data.pop(_ConfigKey.QOS, None)
        if qos is not None:
            _TelegramQoSInput.model_validate(qos)
        return data


class DiscordQoSConfig(ClosedModel):
    """QoS configuration for Discord output coalescing."""

    mode: str = "coalesce_only"  # "off" | "coalesce_only" | "strict"


class _ModeQoSInput(ClosedModel):
    mode: SCALAR_INPUT = None


class WhatsAppQoSConfig(ClosedModel):
    """QoS configuration for WhatsApp (disabled until limits are confirmed)."""

    mode: str = "off"  # "off" | "coalesce_only" | "strict"


class DiscordConfig(ClosedModel):
    """Discord adapter configuration."""

    enabled: FLAG
    token: Annotated[TRUTHY_TEXT, SENSITIVE]
    guild_id: Annotated[OPT_INT_LENIENT, SENSITIVE]
    qos: DiscordQoSConfig = Field(default_factory=DiscordQoSConfig, json_schema_extra={"tier": Tier.INTERNAL})

    @model_validator(mode="before")
    @classmethod
    def _mapping_or_default(cls, value: object) -> object:
        mapped = _mapping_or_empty(value, _DISCORD_MAPPING_ERROR)
        if not isinstance(mapped, Mapping):
            return mapped
        data = dict(mapped)
        qos = data.pop(_ConfigKey.QOS, None)
        if qos is not None:
            _ModeQoSInput.model_validate(qos)
        return data


class WhatsAppConfig(ClosedModel):
    """WhatsApp adapter configuration."""

    enabled: FLAG = False
    phone_number_id: Annotated[OPT_TEXT, SENSITIVE] = None
    access_token: Annotated[OPT_TEXT, SENSITIVE] = None
    webhook_secret: Annotated[OPT_TEXT, SENSITIVE] = None
    verify_token: Annotated[OPT_TEXT, SENSITIVE] = None
    business_number: Annotated[OPT_TEXT, SENSITIVE] = None
    api_version: TEXT = Field(default="v21.0", json_schema_extra={"tier": Tier.INTERNAL})
    template_name: OPT_TEXT = None
    template_language: TEXT = "en_US"
    qos: WhatsAppQoSConfig = Field(default_factory=WhatsAppQoSConfig, json_schema_extra={"tier": Tier.INTERNAL})

    @model_validator(mode="before")
    @classmethod
    def _mapping_or_default(cls, value: object) -> object:
        mapped = _mapping_or_empty(value, _WHATSAPP_MAPPING_ERROR)
        if not isinstance(mapped, Mapping):
            return mapped
        data = dict(mapped)
        qos = data.pop(_ConfigKey.QOS, None)
        if qos is not None:
            _ModeQoSInput.model_validate(qos)
        if _ConfigKey.TEMPLATE_LANGUAGE in data:
            language = data[_ConfigKey.TEMPLATE_LANGUAGE]
            if not isinstance(language, (Mapping, list)):
                data[_ConfigKey.TEMPLATE_LANGUAGE] = _scalar_text_or_raw(language or _EN_US_TEXT)
        else:
            data[_ConfigKey.TEMPLATE_LANGUAGE] = _EN_US_TEXT
        return data


class EmailConfig(ClosedModel):
    """Email (SMTP) sending capability and its typed delivery fields."""

    enabled: FLAG = False
    smtp_username: Annotated[OPT_TEXT, SENSITIVE] = None
    smtp_key: Annotated[OPT_TEXT, SENSITIVE] = None
    email_from: Annotated[OPT_TEXT, SENSITIVE] = None
    reply_to: Annotated[OPT_TEXT, SENSITIVE] = None
    smtp_relay: Annotated[OPT_TEXT, SENSITIVE] = None

    @model_validator(mode="before")
    @classmethod
    def _mapping_or_default(cls, value: object) -> object:
        return _mapping_or_empty(value, _EMAIL_MAPPING_ERROR)


class BackupConfig(ClosedModel):
    """Machine-wide backup destination and credential configuration."""

    aws_access_key_id: Annotated[OPT_TEXT, SENSITIVE] = None
    aws_secret_access_key: Annotated[OPT_TEXT, SENSITIVE] = None
    aws_s3_host: Annotated[OPT_TEXT, SENSITIVE] = None
    aws_s3_region: Annotated[OPT_TEXT, SENSITIVE] = None
    aws_s3_bucket: Annotated[OPT_TEXT, SENSITIVE] = None
    backup_prefix: Annotated[OPT_TEXT, SENSITIVE] = None

    @model_validator(mode="before")
    @classmethod
    def _mapping_or_default(cls, value: object) -> object:
        return _mapping_or_empty(value, _BACKUP_MAPPING_ERROR)


class TTSServiceVoiceConfig(ClosedModel):
    """Voice configuration for a TTS service."""

    name: TEXT
    voice_id: TRUTHY_TEXT = None  # For services like ElevenLabs that need IDs


class VoxCPMVoiceConfig(TTSServiceVoiceConfig):
    """VoxCPM voice overrides, using the same parameter mapping as its service."""

    params: dict[object, object] | None = None  # guard: loose-dict - Provider generation kwargs are dynamic.


class _TTSServiceConfig[Voice: TTSServiceVoiceConfig](ClosedModel):
    """Configuration for a single TTS service."""

    enabled: FLAG
    voices: list[Voice] | None = None
    model: TRUTHY_TEXT = None  # Optional local path or HF repo id
    api_key: TRUTHY_TEXT = None
    # Dynamic provider parameters preserve their original keys and values.
    params: dict[object, object] | None = None  # guard: loose-dict - Model-specific kwargs are dynamic.
    cli_bin: OPT_TEXT = None
    instruct: TEXT = _TTS_DEFAULT_INSTRUCT
    discord_voice: OPT_TEXT = None  # Room voice; None excludes this service from the room chain


class TTSServiceConfig(_TTSServiceConfig[TTSServiceVoiceConfig]):
    """Common provider configuration with name/identifier-only voices."""


class VoxCPMServiceConfig(_TTSServiceConfig[VoxCPMVoiceConfig]):
    """VoxCPM service defaults and per-voice parameter overlays."""

    def effective_params(self, voice: str) -> dict[object, object]:
        """Return an isolated parameter map with the selected voice taking precedence."""
        selected = next((entry for entry in self.voices or [] if (entry.voice_id or entry.name) == voice), None)
        return deepcopy({**(self.params or {}), **(selected.params or {} if selected is not None else {})})


type TTSService = TTSServiceConfig | VoxCPMServiceConfig


def tts_service_model(service_name: str) -> type[TTSServiceConfig] | type[VoxCPMServiceConfig]:
    """Resolve the configuration model owned by a service key."""
    return VoxCPMServiceConfig if service_name == TTSProvider.VOXCPM else TTSServiceConfig


class TTSEventConfig(ClosedModel):
    """Configuration for a TTS event.

    A non-empty ``messages`` list is spoken with one entry chosen at random; an
    empty list falls back to the built-in pool (session_start) or stays silent.
    """

    enabled: FLAG
    messages: list[str] | None = None  # Spoken text pool; one is picked at random


class TTSConfig(ClosedModel):
    """Text-to-speech configuration. Operator-facing — the wizard renders its leaves."""

    # The boot value of the runtime host-playback toggle, not the section's switch: each
    # service and event beneath is governed by its own flag.
    enabled: FLAG = Field(json_schema_extra={"tier": Tier.TUI, GOVERNS_SECTION_METADATA_KEY: False})
    service_priority: list[str] | None = Field(default=None, json_schema_extra={"tier": Tier.TUI})
    events: dict[str, TTSEventConfig] | None = Field(
        default=None,
        json_schema_extra={
            "tier": Tier.TUI,
            "ungoverned_body": "operator-authored keys from the config mapping; membership is not schema-declared",
        },
    )
    services: dict[str, TTSService] | None = Field(
        default=None,
        json_schema_extra={
            "tier": Tier.TUI,
            "ungoverned_body": "operator-authored provider keys from the config mapping; membership is not schema-declared",
        },
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_inputs(cls, value: object) -> object:
        return _normalize_tts_input(value)

    @field_validator(_ConfigKey.SERVICES, mode="before")
    @classmethod
    def _select_service_models(cls, value: object) -> object:
        """Validate each service through its own model before union validation."""
        if not isinstance(value, Mapping):
            return value
        services: dict[str, TTSService] = {}
        errors: list[InitErrorDetails] = []
        for name, settings in value.items():
            try:
                services[str(name)] = tts_service_model(str(name)).model_validate(settings)
            except ValidationError as error:
                for detail in error.errors(include_url=False):
                    errors.append(
                        InitErrorDetails(
                            type=detail[_ValidationDetail.TYPE.value],
                            loc=(str(name), *detail[_ValidationDetail.LOC.value]),
                            input=detail[_ValidationDetail.INPUT.value],
                            ctx=detail.get(_ValidationDetail.CTX.value, {}),
                        )
                    )
        if errors:
            raise ValidationError.from_exception_data(cls.__name__, errors)
        return services


class STTServiceConfig(ClosedModel):
    """Configuration for a single STT service."""

    enabled: FLAG
    model: TRUTHY_TEXT = None  # HF repo id or local path (for parakeet)
    api_key: TRUTHY_TEXT = None
    cli_bin: OPT_TEXT = None


class STTConfig(ClosedModel):
    """Speech-to-text configuration."""

    enabled: FLAG
    service_priority: list[str] | None = None
    services: dict[str, STTServiceConfig] | None = Field(
        default=None,
        json_schema_extra={
            "ungoverned_body": "operator-authored provider keys from the config mapping; membership is not schema-declared"
        },
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_inputs(cls, value: object) -> object:
        return _normalize_stt_input(value)


class ExperimentConfig(ClosedModel):
    """Configuration for a specific experiment.

    Attributes:
        name: Unique identifier for the experiment
        agents: Optional list of agents this experiment applies to.
               If None or empty, the agent dimension is unconstrained.
        adapters: Optional list of adapters this experiment applies to.
               If None or empty, the adapter dimension is unconstrained.
    """

    name: TEXT
    # The builder preserves every list item the operator supplied.
    agents: list[object] | None = None
    # The builder preserves every list item the operator supplied.
    adapters: list[object] | None = None

    @field_validator("agents", "adapters", mode="before")
    @classmethod
    def _preserve_iterable_dimension(cls, value: object) -> list[object] | None:
        if not value:
            return None
        try:
            return list(cast(Iterable[object], value))
        except TypeError:
            raise ValueError(_EXPERIMENT_DIMENSION_ERROR) from None


class TelegramCredsConfig(ClosedModel):
    """Telegram user credentials."""

    user_name: str
    user_id: INT_LENIENT


class WhatsAppCredsConfig(ClosedModel):
    """WhatsApp phone credentials."""

    phone_number: str


class CredsConfig(ClosedModel):
    """Platform credentials container."""

    telegram: TelegramCredsConfig | None = None
    whatsapp: WhatsAppCredsConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_credentials(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        whatsapp = data.get(_ConfigKey.WHATSAPP)
        if isinstance(whatsapp, Mapping) and not whatsapp.get(_ConfigKey.PHONE_NUMBER):
            data[_ConfigKey.WHATSAPP] = None
        return data


class TeleclaudeConfig(ClosedModel):
    """Top-level machine configuration aggregate.

    Each field carries an editability ``tier`` (see the module docstring and
    ``local/projects/teleclaude/policy/config-public-surface``): ``internal`` (the default) for
    constants and runtime-derived values, ``public`` for the ``config.yml``
    surface, ``tui`` for the operator-facing subset the wizard renders. A
    container field's tier is inherited by its unmarked nested leaves.
    """

    computer: ComputerConfig = Field(json_schema_extra={"tier": Tier.TUI})
    polling: PollingConfig = Field(json_schema_extra={"tier": Tier.INTERNAL})
    hook_outbox: HookOutboxConfig = Field(json_schema_extra={"tier": Tier.INTERNAL})
    api: ApiConfig = Field(json_schema_extra={"tier": Tier.INTERNAL})
    daemon: DaemonConfig = Field(json_schema_extra={"tier": Tier.TUI})
    redis: RedisConfig = Field(json_schema_extra={"tier": Tier.TUI})
    event_reliability: EventReliabilityConfig = Field(json_schema_extra={"tier": Tier.INTERNAL})
    telegram: TelegramConfig = Field(json_schema_extra={"tier": Tier.TUI, SCOPE_METADATA_KEY: Scope.MASTER})
    discord: DiscordConfig = Field(json_schema_extra={"tier": Tier.TUI})
    creds: CredsConfig = Field(json_schema_extra={"tier": Tier.INTERNAL})
    agents: dict[AgentName, AgentConfig] = Field(json_schema_extra={"tier": Tier.PUBLIC})
    default_agent: AgentName = Field(json_schema_extra={"tier": Tier.PUBLIC})
    terminal: TerminalConfig = Field(json_schema_extra={"tier": Tier.INTERNAL})
    whatsapp: WhatsAppConfig = Field(
        default_factory=WhatsAppConfig, json_schema_extra={"tier": Tier.TUI, SCOPE_METADATA_KEY: Scope.MASTER}
    )
    email: EmailConfig = Field(
        default_factory=EmailConfig, json_schema_extra={"tier": Tier.TUI, SCOPE_METADATA_KEY: Scope.MASTER}
    )
    backup: BackupConfig = Field(default_factory=BackupConfig, json_schema_extra={"tier": Tier.TUI})
    tts: TTSConfig | None = Field(default=None, json_schema_extra={"tier": Tier.TUI})
    stt: STTConfig | None = Field(default=None, json_schema_extra={"tier": Tier.TUI})
    chiptunes: ChiptunesConfig | None = Field(default=None, json_schema_extra={"tier": Tier.TUI})
    process_janitor: ProcessJanitorConfig = Field(
        default_factory=ProcessJanitorConfig, json_schema_extra={"tier": Tier.INTERNAL}
    )
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig, json_schema_extra={"tier": Tier.PUBLIC})
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig, json_schema_extra={"tier": Tier.PUBLIC})
    database_url: Annotated[str | None, SENSITIVE] = Field(default=None, json_schema_extra={"tier": Tier.PUBLIC})
    summarizer: SummarizerConfig | None = Field(default=None, json_schema_extra={"tier": Tier.TUI})
    load_id: str = Field(default="", json_schema_extra={"tier": Tier.INTERNAL})
    experiments: list[ExperimentConfig] = Field(
        default_factory=list,
        json_schema_extra={
            "tier": Tier.INTERNAL,
            "ungoverned_body": "config-authored list; entries are positional instances, not schema fields",
        },
    )
    remote_computers: list[RemoteComputerConfig] = Field(
        default_factory=list,
        json_schema_extra={
            "tier": Tier.INTERNAL,
            "ungoverned_body": "config-authored mapping parsed into a list; entries are instances, not schema fields",
        },
    )

    def is_experiment_enabled(self, name: str, agent: str | None = None, adapter: str | None = None) -> bool:
        """Check if an experiment is enabled for a given agent/adapter combination.

        Multiple entries with the same name are OR'd together.
        Within each entry, dimensions (agents, adapters) are AND'd.
        When the caller omits a dimension, that dimension is not checked
        (optimistic match — useful when the coordinator asks "does any adapter want this?").

        Args:
            name: Experiment name to check
            agent: Optional agent key to match against (e.g., "gemini")
            adapter: Optional adapter key to match against (e.g., "discord")

        Returns:
            True if any matching experiment entry is found
        """
        for exp in self.experiments:
            if exp.name != name:
                continue
            # Agent dimension: strict — entry requires agent match when constrained
            if exp.agents:
                if not agent or agent not in exp.agents:
                    continue
            # Adapter dimension: optimistic when caller omits adapter
            # (coordinator asking "does any adapter want this?")
            if exp.adapters and adapter and adapter not in exp.adapters:
                continue
            return True
        return False

    def scope_applies(self, path: str) -> bool:
        """Return whether a machine-schema path's declared scope applies here."""
        scope = resolve_schema_scope(type(self), path)
        return scope is not Scope.MASTER or self.computer.is_master

    def master_scope_applies(self) -> bool:
        """Return whether this computer is declared to apply master-scoped behavior."""
        return self.computer.is_master

    def availability(self, path: str) -> AvailabilityAnswer:
        """Return the configuration owner's readiness answer for one schema path."""
        return configuration_availability(self, path)

    def master_scoped_not_applicable(self) -> tuple[str, ...]:
        """Return minimal dotted master-scoped paths that do not apply on this computer."""
        if self.computer.is_master:
            return ()
        return tuple(PATH_SEPARATOR.join(path) for path in master_scoped_paths(type(self)))

    @model_validator(mode="after")
    def _settle_effective_enabled(self) -> Self:
        settle_effective_enabled(self, is_master=self.computer.is_master)
        return self

    @model_validator(mode="wrap")
    @classmethod
    def _derive_runtime_fields_and_collect_errors(
        cls,
        data: object,
        handler: ModelWrapValidatorHandler[Self],
        info: ValidationInfo,
    ) -> Self:
        issues: list[ConfigValidationIssue] = []
        candidate = data
        if info.context is not None:
            candidate, issues = cast(AggregateInputDerivation, info.context).prepare(data)
        try:
            aggregate = handler(candidate)
        except ValidationError as error:
            error_lines = error.errors(include_url=False)
            title = error.title
        else:
            if not issues:
                return aggregate
            error_lines = []
            title = cls.__name__
        details: list[InitErrorDetails] = [
            InitErrorDetails(
                type=PydanticCustomError(issue.code, issue.message),  # pyright: ignore[reportArgumentType] - preserved validation errors are dynamic
                loc=issue.loc,
                input=issue.input,
            )
            for issue in issues
        ]
        details.extend(
            InitErrorDetails(
                type=PydanticCustomError(line["type"], line["msg"]),  # pyright: ignore[reportArgumentType] - preserved validation errors are dynamic
                loc=line["loc"],
                input=line["input"],
            )
            for line in error_lines
        )
        raise ValidationError.from_exception_data(title, details)
