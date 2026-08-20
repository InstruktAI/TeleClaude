"""Configuration schema dataclasses.

The typed shapes the application reads configuration through. Parsing from raw
YAML/.env into these models lives in the package ``__init__``; these are the
schema definitions only.

Editability is opt-in and code-led: every field carries a ``tier`` in its
``metadata`` — ``internal`` (the default), ``public``, or ``tui`` — declaring what
reaches humans. A field with no marker is ``internal``: absent from the generated
``templates/config.yml`` sample, absent from the config TUI, not human-editable.
``public`` fields are the ``config.yml`` surface (in the generated sample);
``tui`` fields are the operator-facing subset the wizard renders. A container
field's tier is inherited by its unmarked nested leaves. The field tiers are the
single authority for what is public — the defaults blob and the sample follow
from them. See ``project/policy/config-public-surface``.

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

from dataclasses import dataclass, field
from enum import StrEnum

from teleclaude.config._chiptunes import ChiptunesConfig
from teleclaude.config._remote_computers import RemoteComputerConfig
from teleclaude.config._summarizer import SummarizerConfig
from teleclaude.config.tiers import Tier


@dataclass
class TrustedDir:
    """Represents a trusted directory with metadata for AI understanding.

    Attributes:
        name: Human-readable identifier (e.g., "development", "documents", "projects")
        desc: Purpose description for AI context (e.g., "dev projects", "personal docs"). Can be empty.
        path: Absolute file system path to the directory
    """

    name: str
    desc: str
    path: str
    discord_forum: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})


@dataclass
class PollingConfig:
    """Agent output polling intervals."""

    directory_check_interval: int
    output_cadence_s: float = 1.0


@dataclass
class ComputerConfig:
    name: str = field(metadata={"tier": Tier.TUI})
    user: str = field(metadata={"tier": Tier.INTERNAL})
    role: str = field(metadata={"tier": Tier.TUI})
    timezone: str = field(metadata={"tier": Tier.TUI})
    default_working_dir: str = field(metadata={"tier": Tier.INTERNAL})
    help_desk_dir: str = field(metadata={"tier": Tier.INTERNAL})
    is_master: bool = field(metadata={"tier": Tier.TUI})
    # In the sample but not the wizard: editing the trusted-dir list is a file-level task.
    trusted_dirs: list[TrustedDir] = field(
        metadata={
            "tier": Tier.PUBLIC,
            "ungoverned_body": "config-authored list; entries are positional instances, not schema fields",
        }
    )
    # Optional LAN address override; auto-detected when unset.
    host: str | None = field(default=None, metadata={"tier": Tier.TUI})
    tmux_binary: str = field(default="tmux", metadata={"tier": Tier.INTERNAL})
    is_ingress_node: bool = field(default=False, metadata={"tier": Tier.TUI})

    def get_all_trusted_dirs(self) -> list[TrustedDir]:
        """Get all trusted directories from config, deduplicated by path."""
        seen_paths: set[str] = set()
        all_dirs: list[TrustedDir] = []
        for trusted_dir in self.trusted_dirs:
            if trusted_dir.path not in seen_paths:
                all_dirs.append(trusted_dir)
                seen_paths.add(trusted_dir.path)
        return all_dirs


@dataclass
class ModelChainEntry:
    """One declared launch-model fallback entry: model label, opaque launch
    flags, and an optional per-launch patch parameter map (JSON of loader-id
    -> config) rendered into the session's ephemeral --patch overlay."""

    model: str
    flags: str
    patch: str = ""


@dataclass
class AgentConfig:
    """Configuration for a specific AI agent."""

    binary: str = field(metadata={"tier": Tier.INTERNAL})  # Resolved by runtime policy
    profiles: dict[str, str] = field(metadata={"tier": Tier.PUBLIC})
    session_dir: str = field(metadata={"tier": Tier.INTERNAL})
    log_pattern: str = field(metadata={"tier": Tier.INTERNAL})
    mode_chains: dict[str, list[ModelChainEntry]] = field(metadata={"tier": Tier.INTERNAL})
    model_chains: dict[str, list[ModelChainEntry]] = field(metadata={"tier": Tier.PUBLIC})
    exec_subcommand: str = field(metadata={"tier": Tier.INTERNAL})
    # Flag to add before prompt for interactive mode (e.g., "-i")
    interactive_flag: str = field(metadata={"tier": Tier.INTERNAL})
    # Flag for non-interactive/pipe mode (e.g., "-p")
    non_interactive_flag: str = field(metadata={"tier": Tier.INTERNAL})
    resume_template: str = field(metadata={"tier": Tier.INTERNAL})
    continue_template: str = field(default="", metadata={"tier": Tier.INTERNAL})
    prompt_at_launch: bool = field(default=False, metadata={"tier": Tier.INTERNAL})
    model_via_launch_patch: bool = field(default=False, metadata={"tier": Tier.INTERNAL})
    restricted_sandbox_mode: str = field(default="", metadata={"tier": Tier.INTERNAL})
    enabled: bool = field(default=True, metadata={"tier": Tier.TUI})
    # git --author value; from constants.GIT_AUTHOR_IDENTITIES at load time
    git_identity: str | None = field(default=None, metadata={"tier": Tier.INTERNAL})

    def get_command(self, profile: str = "default") -> str:
        """Assembled base command: binary + profile flags."""
        flags = self.profiles.get(profile)
        if flags is None:
            # Fallback to default if profile not found
            flags = self.profiles.get("default", "")
        return f"{self.binary} {flags}".strip()

    @property
    def command(self) -> str:
        """Assembled base command: binary + default flags."""
        return self.get_command("default")


@dataclass
class RedisConfig:
    """Redis configuration with user-configurable and internal settings."""

    url: str
    password: str | None
    max_connections: int
    socket_timeout: int
    message_stream_maxlen: int
    output_stream_maxlen: int
    output_stream_ttl: int


@dataclass
class EventReliabilityConfig:
    """Event processor reliability controls."""

    idle_threshold_ms: int
    max_attempts: int
    sweep_interval_ms: int
    dlq_destination: str


STALL_THRESHOLD_SECONDS = 150


@dataclass
class TelegramQoSConfig:
    """QoS configuration for Telegram output pacing and coalescing."""

    enabled: bool = True
    group_mpm: int = 20
    output_budget_ratio: float = 0.8
    reserve_mpm: int = 4
    min_session_tick_s: float = 3.0
    active_emitter_window_s: float = 10.0
    active_emitter_ema_alpha: float = 0.2
    rounding_ms: int = 100


@dataclass
class TelegramConfig:
    """Telegram adapter configuration."""

    enabled: bool = False
    qos: TelegramQoSConfig = field(default_factory=TelegramQoSConfig, metadata={"tier": Tier.INTERNAL})


@dataclass
class DiscordQoSConfig:
    """QoS configuration for Discord output coalescing."""

    mode: str = "coalesce_only"  # "off" | "coalesce_only" | "strict"


@dataclass
class WhatsAppQoSConfig:
    """QoS configuration for WhatsApp (disabled until limits are confirmed)."""

    mode: str = "off"  # "off" | "coalesce_only" | "strict"


@dataclass
class DiscordConfig:
    """Discord adapter configuration."""

    enabled: bool
    token: str | None
    guild_id: int | None
    help_desk_channel_id: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    escalation_channel_id: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    all_sessions_channel_id: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    operator_chat_channel_id: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    announcements_channel_id: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    general_channel_id: int | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    categories: dict[str, int] | None = field(default=None, metadata={"tier": Tier.INTERNAL})
    qos: DiscordQoSConfig = field(default_factory=DiscordQoSConfig, metadata={"tier": Tier.INTERNAL})


@dataclass
class WhatsAppConfig:
    """WhatsApp adapter configuration."""

    enabled: bool = False
    phone_number_id: str | None = None
    access_token: str | None = None
    webhook_secret: str | None = None
    verify_token: str | None = None
    api_version: str = field(default="v21.0", metadata={"tier": Tier.INTERNAL})
    template_name: str | None = None
    template_language: str = "en_US"
    qos: WhatsAppQoSConfig = field(default_factory=WhatsAppQoSConfig, metadata={"tier": Tier.INTERNAL})


@dataclass
class EmailConfig:
    """Email (SMTP) sending capability. Credentials live in .env; this is the toggle.

    Off by default — explicit opt-in like every other capability. Required-field
    validation and the send gate enforce that an enabled email is configured.
    """

    enabled: bool = False


@dataclass
class TTSServiceVoiceConfig:
    """Voice configuration for a TTS service."""

    name: str
    voice_id: str | None = None  # For services like ElevenLabs that need IDs


@dataclass
class TTSServiceConfig:
    """Configuration for a single TTS service."""

    enabled: bool
    voices: list[TTSServiceVoiceConfig] | None = None
    model: str | None = None  # Optional local path or HF repo id
    params: dict[str, object] | None = None  # guard: loose-dict - Model-specific kwargs are dynamic.


@dataclass
class TTSEventConfig:
    """Configuration for a TTS event.

    A non-empty ``messages`` list is spoken with one entry chosen at random; an
    empty list falls back to the built-in pool (session_start) or stays silent.
    """

    enabled: bool
    messages: list[str] | None = None  # Spoken text pool; one is picked at random


@dataclass
class TTSConfig:
    """Text-to-speech configuration. Operator-facing — the wizard renders its leaves."""

    enabled: bool = field(metadata={"tier": Tier.TUI})
    service_priority: list[str] | None = field(default=None, metadata={"tier": Tier.TUI})
    events: dict[str, TTSEventConfig] | None = field(
        default=None,
        metadata={
            "tier": Tier.TUI,
            "ungoverned_body": "operator-authored keys from the config mapping; membership is not schema-declared",
        },
    )
    services: dict[str, TTSServiceConfig] | None = field(
        default=None,
        metadata={
            "tier": Tier.TUI,
            "ungoverned_body": "operator-authored provider keys from the config mapping; membership is not schema-declared",
        },
    )


@dataclass
class STTServiceConfig:
    """Configuration for a single STT service."""

    enabled: bool
    model: str | None = None  # HF repo id or local path (for parakeet)


@dataclass
class STTConfig:
    """Speech-to-text configuration."""

    enabled: bool
    service_priority: list[str] | None = None
    services: dict[str, STTServiceConfig] | None = field(
        default=None,
        metadata={
            "ungoverned_body": "operator-authored provider keys from the config mapping; membership is not schema-declared",
        },
    )


@dataclass
class ProcessJanitorConfig:
    """Process janitor timing and safety defaults."""

    scan_interval_seconds: int = 300
    default_signature_ttl_seconds: int = 3600
    lease_ttl_seconds: int = 1800
    dry_run_default: bool = True
    reap_revalidation_seconds: int = 3600


@dataclass
class WorkflowAutostartConfig:
    """Per-kind automatic lifecycle-runner dispatch policy (off by default)."""

    feature: bool = False
    change: bool = False
    bug: bool = False
    task: bool = False


class WorkflowRunnerMode(StrEnum):
    """Master switch over the lifecycle runner's autonomous dispatch path."""

    AUTOSTART = "autostart"
    MANUAL = "manual"


@dataclass
class WorkflowConfig:
    """Daemon-runtime lifecycle-runner control plane."""

    autostart: WorkflowAutostartConfig = field(default_factory=WorkflowAutostartConfig, metadata={"tier": Tier.PUBLIC})
    runner: WorkflowRunnerMode = field(default=WorkflowRunnerMode.AUTOSTART, metadata={"tier": Tier.PUBLIC})
    max_todo_dispatch: int = field(default=5, metadata={"tier": Tier.PUBLIC})


class ReleaseChannel(StrEnum):
    """TeleClaude self-update release channel."""

    ALPHA = "alpha"
    BETA = "beta"
    STABLE = "stable"


@dataclass
class DeploymentConfig:
    """Release channel and version pinning for TeleClaude self-update.

    Machine-wide: the release channel governs this host's self-update — installed
    once per host, not per project. ``stable`` requires a non-empty ``pinned_minor``.
    """

    channel: ReleaseChannel = ReleaseChannel.ALPHA
    pinned_minor: str = ""

    def __post_init__(self) -> None:
        if self.channel == ReleaseChannel.STABLE and not self.pinned_minor:
            raise ValueError("pinned_minor is required and must be non-empty when channel=stable")


@dataclass
class TerminalConfig:
    """Terminal display settings."""

    strip_ansi: bool = True


@dataclass
class ExperimentConfig:
    """Configuration for a specific experiment.

    Attributes:
        name: Unique identifier for the experiment
        agents: Optional list of agents this experiment applies to.
               If None or empty, the agent dimension is unconstrained.
        adapters: Optional list of adapters this experiment applies to.
               If None or empty, the adapter dimension is unconstrained.
    """

    name: str
    agents: list[str] | None = None
    adapters: list[str] | None = None


@dataclass
class TelegramCredsConfig:
    """Telegram user credentials."""

    user_name: str
    user_id: int


@dataclass
class WhatsAppCredsConfig:
    """WhatsApp phone credentials."""

    phone_number: str


@dataclass
class CredsConfig:
    """Platform credentials container."""

    telegram: TelegramCredsConfig | None = None
    whatsapp: WhatsAppCredsConfig | None = None


@dataclass
class TeleclaudeConfig:
    """Top-level machine configuration aggregate.

    Each field carries an editability ``tier`` (see the module docstring and
    ``project/policy/config-public-surface``): ``internal`` (the default) for
    constants and runtime-derived values, ``public`` for the ``config.yml``
    surface, ``tui`` for the operator-facing subset the wizard renders. A
    container field's tier is inherited by its unmarked nested leaves.
    """

    computer: ComputerConfig = field(metadata={"tier": Tier.TUI})
    polling: PollingConfig = field(metadata={"tier": Tier.INTERNAL})
    redis: RedisConfig = field(metadata={"tier": Tier.TUI})
    event_reliability: EventReliabilityConfig = field(metadata={"tier": Tier.INTERNAL})
    telegram: TelegramConfig = field(metadata={"tier": Tier.TUI})
    discord: DiscordConfig = field(metadata={"tier": Tier.TUI})
    creds: CredsConfig = field(metadata={"tier": Tier.INTERNAL})
    agents: dict[str, AgentConfig] = field(
        metadata={
            "tier": Tier.PUBLIC,
            "ungoverned_body": (
                "closed vocabulary modelled as a str-keyed map: the keys are exactly the known agent "
                "names, enforced at load by _validate_known_agent_keys rather than by the type. Governing "
                "AgentConfig leaf-by-leaf requires keying this map by that enum first."
            ),
        }
    )
    default_agent: str = field(metadata={"tier": Tier.PUBLIC})
    terminal: TerminalConfig = field(metadata={"tier": Tier.INTERNAL})
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig, metadata={"tier": Tier.TUI})
    email: EmailConfig = field(default_factory=EmailConfig, metadata={"tier": Tier.PUBLIC})
    tts: TTSConfig | None = field(default=None, metadata={"tier": Tier.TUI})
    stt: STTConfig | None = field(default=None, metadata={"tier": Tier.TUI})
    chiptunes: ChiptunesConfig | None = field(default=None, metadata={"tier": Tier.TUI})
    process_janitor: ProcessJanitorConfig = field(
        default_factory=ProcessJanitorConfig, metadata={"tier": Tier.INTERNAL}
    )
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig, metadata={"tier": Tier.PUBLIC})
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig, metadata={"tier": Tier.PUBLIC})
    summarizer: SummarizerConfig | None = field(default=None, metadata={"tier": Tier.TUI})
    experiments: list[ExperimentConfig] = field(
        default_factory=list,
        metadata={
            "tier": Tier.INTERNAL,
            "ungoverned_body": "config-authored list; entries are positional instances, not schema fields",
        },
    )
    remote_computers: list[RemoteComputerConfig] = field(
        default_factory=list,
        metadata={
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
