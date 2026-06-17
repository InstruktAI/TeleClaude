"""Configuration schema dataclasses.

The typed shapes the application reads configuration through. Parsing from raw
YAML/.env into these models lives in the package ``__init__``; these are the
schema definitions only.
"""

from dataclasses import dataclass, field

from teleclaude.config._chiptunes import ChiptunesConfig
from teleclaude.config._remote_computers import RemoteComputerConfig
from teleclaude.config._summarizer import SummarizerConfig


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
    discord_forum: int | None = field(default=None, metadata={"exclude_from_tui": True})


@dataclass
class PollingConfig:
    """Agent output polling intervals."""

    directory_check_interval: int
    output_cadence_s: float = 1.0


@dataclass
class ComputerConfig:
    name: str
    user: str = field(metadata={"exclude_from_tui": True})
    role: str
    timezone: str
    default_working_dir: str = field(metadata={"exclude_from_tui": True})
    help_desk_dir: str = field(metadata={"exclude_from_tui": True})
    is_master: bool
    trusted_dirs: list[TrustedDir] = field(metadata={"exclude_from_tui": True})
    host: str | None = field(
        default=None, metadata={"exclude_from_tui": True}
    )  # Detected LAN IP at runtime; not operator-editable.
    tmux_binary: str = field(default="tmux", metadata={"exclude_from_tui": True})

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
class AgentConfig:
    """Configuration for a specific AI agent."""

    binary: str  # Resolved by runtime policy (not user-configurable)
    profiles: dict[str, str]  # System-controlled profiles, from AGENT_PROTOCOL
    session_dir: str
    log_pattern: str
    model_flags: dict[str, str]
    exec_subcommand: str
    interactive_flag: str  # Flag to add before prompt for interactive mode (e.g., "-i")
    non_interactive_flag: str  # Flag for non-interactive/pipe mode (e.g., "-p")
    resume_template: str
    continue_template: str = ""
    enabled: bool = True

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
    qos: TelegramQoSConfig = field(default_factory=TelegramQoSConfig, metadata={"exclude_from_tui": True})


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
    help_desk_channel_id: int | None = field(default=None, metadata={"exclude_from_tui": True})
    escalation_channel_id: int | None = field(default=None, metadata={"exclude_from_tui": True})
    all_sessions_channel_id: int | None = field(default=None, metadata={"exclude_from_tui": True})
    operator_chat_channel_id: int | None = field(default=None, metadata={"exclude_from_tui": True})
    announcements_channel_id: int | None = field(default=None, metadata={"exclude_from_tui": True})
    general_channel_id: int | None = field(default=None, metadata={"exclude_from_tui": True})
    categories: dict[str, int] | None = field(default=None, metadata={"exclude_from_tui": True})
    qos: DiscordQoSConfig = field(default_factory=DiscordQoSConfig, metadata={"exclude_from_tui": True})


@dataclass
class WhatsAppConfig:
    """WhatsApp adapter configuration."""

    enabled: bool = False
    phone_number_id: str | None = None
    access_token: str | None = None
    webhook_secret: str | None = None
    verify_token: str | None = None
    api_version: str = field(default="v21.0", metadata={"exclude_from_tui": True})
    template_name: str | None = None
    template_language: str = "en_US"
    qos: WhatsAppQoSConfig = field(default_factory=WhatsAppQoSConfig, metadata={"exclude_from_tui": True})


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

    Supports either a single message or a list of messages (picks randomly).
    """

    enabled: bool
    message: str | None = None
    messages: list[str] | None = None  # For random selection (e.g., startup greetings)


@dataclass
class TTSConfig:
    """Text-to-speech configuration."""

    enabled: bool
    service_priority: list[str] | None = None
    events: dict[str, TTSEventConfig] | None = None
    services: dict[str, TTSServiceConfig] | None = None


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
    services: dict[str, STTServiceConfig] | None = None


@dataclass
class ProcessJanitorConfig:
    """Process janitor timing and safety defaults."""

    scan_interval_seconds: int = 300
    default_signature_ttl_seconds: int = 3600
    lease_ttl_seconds: int = 1800
    dry_run_default: bool = True


@dataclass
class WorkflowAutostartConfig:
    """Per-kind automatic lifecycle-runner dispatch policy (off by default)."""

    feature: bool = False
    change: bool = False
    bug: bool = False
    task: bool = False


@dataclass
class WorkflowConfig:
    """Daemon-runtime lifecycle-runner control plane."""

    autostart: WorkflowAutostartConfig = field(default_factory=WorkflowAutostartConfig)
    max_todo_dispatch: int = 5


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
class Config:
    """Top-level application configuration."""

    computer: ComputerConfig
    polling: PollingConfig
    redis: RedisConfig
    event_reliability: EventReliabilityConfig
    telegram: TelegramConfig
    discord: DiscordConfig
    creds: CredsConfig
    agents: dict[str, AgentConfig]
    default_agent: str
    terminal: TerminalConfig
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    tts: TTSConfig | None = None
    stt: STTConfig | None = None
    chiptunes: ChiptunesConfig | None = None
    process_janitor: ProcessJanitorConfig = field(default_factory=ProcessJanitorConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    summarizer: SummarizerConfig | None = None
    experiments: list[ExperimentConfig] = field(default_factory=list)
    remote_computers: list[RemoteComputerConfig] = field(default_factory=list)

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
