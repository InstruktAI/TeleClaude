"""Shared constants, data classes, and utility functions for the config view."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, Field
from rich.style import Style

from teleclaude.cli.config_handlers import EnvVarStatus
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, get_neutral_color
from teleclaude.config.schema import PersonEntry


class Subtab(StrEnum):
    """Config-view subtab identifiers."""

    COMPUTER = "Computer"
    PEOPLE = "People"
    ADAPTERS = "Adapters"
    PROVIDERS = "Providers"
    SUMMARIZER = "Summarizer"
    TTS_STT = "TTS/STT"
    ENV = "Env"


# Ordered tabs for index-based navigation (active_subtab).
_SUBTABS = tuple(Subtab)


class TtsSttConfig(BaseModel):
    """Pydantic model for dynamic reflection of TTS/STT configurations."""

    stt_enabled: bool = Field(default=True, description="Enable Speech-to-Text")
    stt_service_priority: list[str] = Field(
        default_factory=lambda: ["parakeet", "openai"],
        description="Speech-to-Text engine priorities",
    )
    tts_enabled: bool = Field(default=False, description="Enable Text-to-Speech")
    tts_service_priority: list[str] = Field(
        default_factory=lambda: ["voxcpm", "kokoro", "qwen3", "openai", "elevenlabs", "macos", "pyttsx3"],
        description="Text-to-Speech engine priorities",
    )


class TelegramAdapterConfig(BaseModel):
    """Telegram admin adapter configuration. The token is the TELEGRAM_BOT_TOKEN env secret."""

    enabled: bool = Field(default=False, description="Enable for customers and personal agents")
    bot_token: str = Field(default="", description="Telegram Bot API token from @BotFather")


class DiscordAdapterConfig(BaseModel):
    """Discord admin adapter configuration."""

    enabled: bool = Field(default=False, description="Enable for admins")
    token: str = Field(default="", description="Discord bot token from the Developer Portal")
    guild_id: str = Field(default="", description="Discord server (guild) ID")


class WhatsAppAdapterConfig(BaseModel):
    """WhatsApp business adapter configuration."""

    enabled: bool = Field(default=False, description="Enable for customers and personal agents")
    phone_number_id: str = Field(default="", description="Meta WhatsApp business phone number ID")
    access_token: str = Field(default="", description="Meta system-user access token")
    webhook_secret: str = Field(default="", description="App secret for webhook signature verification")
    verify_token: str = Field(default="", description="Shared token for webhook challenge-response")
    template_name: str = Field(default="", description="Approved template for 24h-window messages")
    template_language: str = Field(default="en_US", description="Template language code")


class EmailAdapterConfig(BaseModel):
    """Email via SMTP relay (e.g. Brevo). All values are .env secrets/settings."""

    email_from: str = Field(default="", description="Sender identity (Name <addr>)")
    email_replyto: str = Field(default="", description="Reply-To header")
    smtp_username: str = Field(default="", description="SMTP relay username")
    smtp_key: str = Field(default="", description="SMTP relay key / password")
    smtp_relay: str = Field(default="", description="SMTP relay host:port")


class BackupAdapterConfig(BaseModel):
    """S3 backup target. Credentials are .env secrets."""

    aws_access_key_id: str = Field(default="", description="S3 access key id")
    aws_secret_access_key: str = Field(default="", description="S3 secret access key")
    aws_s3_host: str = Field(default="", description="S3 endpoint host")
    aws_s3_region: str = Field(default="", description="S3 region")
    aws_s3_bucket: str = Field(default="", description="S3 bucket name")
    backup_prefix: str = Field(default="", description="Key prefix for backups")


class FirecrawlAdapterConfig(BaseModel):
    """Firecrawl web-scraping provider."""

    api_key: str = Field(default="", description="Firecrawl API key (web scraping)")


class AIKeysConfig(BaseModel):
    """LLM provider API keys (summarizer, agents, Gemini/Nano Banana image gen)."""

    anthropic_api_key: str = Field(default="", description="Anthropic API key (Claude summarizer)")
    openai_api_key: str = Field(default="", description="OpenAI API key (Whisper STT, summarizer fallback)")
    google_api_key: str = Field(default="", description="Google API key (Gemini agent, Nano Banana, summarizer)")


class AdaptersConfig(BaseModel):
    """Messaging-platform adapters."""

    discord: DiscordAdapterConfig = Field(default_factory=DiscordAdapterConfig)
    telegram: TelegramAdapterConfig = Field(default_factory=TelegramAdapterConfig)
    whatsapp: WhatsAppAdapterConfig = Field(default_factory=WhatsAppAdapterConfig)


class ProvidersConfig(BaseModel):
    """Service providers (LLM keys, email, backup, web scraping)."""

    ai: AIKeysConfig = Field(default_factory=AIKeysConfig)
    email: EmailAdapterConfig = Field(default_factory=EmailAdapterConfig)
    backup: BackupAdapterConfig = Field(default_factory=BackupAdapterConfig)
    firecrawl: FirecrawlAdapterConfig = Field(default_factory=FirecrawlAdapterConfig)


class SummarizerTabConfig(BaseModel):
    """Summary/title provider settings, surfaced in the Summarizer subtab.

    local_base_url is the ${SUMMARIZER_LOCAL_BASE_URL} env secret; the rest persist
    to the config.yml summarizer section.
    """

    local_enabled: bool = Field(default=False, description="Use a local OpenAI-compatible summarizer first")
    local_base_url: str = Field(default="", description="Local OpenAI-compatible endpoint (e.g. LM Studio)")
    local_model: str = Field(default="", description="Model id loaded in the local server")
    provider_priority: list[str] = Field(
        default_factory=list, description="Cloud fallback order: openai/anthropic/google"
    )
    openai_model: str = Field(default="", description="OpenAI model for summaries")
    anthropic_model: str = Field(default="", description="Anthropic model for summaries")
    google_model: str = Field(default="", description="Google Gemini model for summaries")


_PERSON_EDITABLE_FIELDS = ("name", "email", "role", "username", "preferences", "expertise")
_VALID_ROLES = ("admin", "member", "contributor", "newcomer")


class AdapterTab(StrEnum):
    """Adapter sub-tab identifiers."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    AI_KEYS = "ai_keys"
    WHATSAPP = "whatsapp"


# Ordered adapter tabs for index-based navigation (active_adapter_tab).
_ADAPTER_TABS = tuple(AdapterTab)
_ADAPTER_LABELS = {
    AdapterTab.TELEGRAM: "Telegram",
    AdapterTab.DISCORD: "Discord",
    AdapterTab.AI_KEYS: "AI + Voice",
    AdapterTab.WHATSAPP: "WhatsApp",
}
_ADAPTER_ENV_KEYS = {
    AdapterTab.TELEGRAM: ("telegram",),
    AdapterTab.DISCORD: ("discord",),
    AdapterTab.AI_KEYS: ("ai", "voice"),
    AdapterTab.WHATSAPP: ("whatsapp",),
}

# Styles


def _normal_style() -> Style:
    """Normal text style — adapts to dark/light mode."""
    return Style(color=get_neutral_color("highlight"))


_DIM = Style(color="#727578")
_OK = Style(color="#5faf5f")
_FAIL = Style(color="#d75f5f")
_WARN = Style(color="#d7af5f")
_INFO = Style(color="#87afd7")
_SEP = Style(color=CONNECTOR_COLOR)
_TAB_ACTIVE = Style(bold=True, reverse=True)
_TAB_INACTIVE = Style(color="#808080")

AdapterStatus = Literal["configured", "partial", "unconfigured"]


@dataclass(frozen=True)
class AdapterSectionProjection:
    """Computed adapter section state for rendering and guided flow."""

    key: AdapterTab
    label: str
    env_statuses: list[EnvVarStatus]
    status: AdapterStatus
    configured_count: int
    total_count: int


@dataclass(frozen=True)
class GuidedStep:
    """Deterministic guided mode step."""

    subtab: Subtab
    title: str
    adapter_tab: str | None = None


_GUIDED_STEPS: tuple[GuidedStep, ...] = (
    GuidedStep(subtab=Subtab.COMPUTER, title="System Identity"),
    GuidedStep(subtab=Subtab.PEOPLE, title="Admin Setup"),
    GuidedStep(subtab=Subtab.ADAPTERS, title="Configure Adapters"),
    GuidedStep(subtab=Subtab.PROVIDERS, title="Configure Providers"),
    GuidedStep(subtab=Subtab.SUMMARIZER, title="Configure Summarizer"),
    GuidedStep(subtab=Subtab.TTS_STT, title="Configure TTS/STT"),
    GuidedStep(subtab=Subtab.ENV, title="Review Environment"),
)


def classify_adapter_status(env_statuses: list[EnvVarStatus]) -> AdapterStatus:
    """Classify adapter setup status from env var state."""
    if not env_statuses:
        return "unconfigured"
    configured_count = sum(1 for status in env_statuses if status.is_set)
    if configured_count == 0:
        return "unconfigured"
    if configured_count == len(env_statuses):
        return "configured"
    return "partial"


def project_adapter_sections(env_data: list[EnvVarStatus]) -> list[AdapterSectionProjection]:
    """Build adapter section projections for the configured tab set."""
    sections: list[AdapterSectionProjection] = []
    for key in _ADAPTER_TABS:
        adapter_keys = _ADAPTER_ENV_KEYS[key]
        statuses = [status for status in env_data if status.info.adapter in adapter_keys]
        configured_count = sum(1 for status in statuses if status.is_set)
        sections.append(
            AdapterSectionProjection(
                key=key,
                label=_ADAPTER_LABELS.get(key, key),
                env_statuses=statuses,
                status=classify_adapter_status(statuses),
                configured_count=configured_count,
                total_count=len(statuses),
            )
        )
    return sections


def get_allowed_values_for_field(field_name: str) -> list[str] | None:
    """Extract Literal allowed values from PersonEntry schema or Union annotations."""

    def unpack_union(t: Any) -> list[Any]:
        if get_origin(t) in (Union, UnionType):
            return list(get_args(t))
        return [t]

    if ":" in field_name:
        parent, _ = field_name.split(":", 1)
        if parent in PersonEntry.model_fields:
            ann = PersonEntry.model_fields[parent].annotation
            # Unpack Optionals/Unions to find dict type
            dict_types = [t for t in unpack_union(ann) if get_origin(t) is dict or t is dict]
            if dict_types:
                dict_ann = dict_types[0]
                args = get_args(dict_ann)
                if len(args) == 2:
                    val_type = args[1]
                    for option in unpack_union(val_type):
                        if get_origin(option) is Literal:
                            return list(get_args(option))
    else:
        if field_name in PersonEntry.model_fields:
            ann = PersonEntry.model_fields[field_name].annotation
            for option in unpack_union(ann):
                if get_origin(option) is Literal:
                    return list(get_args(option))
    return None


__all__ = [
    "_ADAPTER_ENV_KEYS",
    "_ADAPTER_LABELS",
    "_ADAPTER_TABS",
    "_DIM",
    "_FAIL",
    "_GUIDED_STEPS",
    "_INFO",
    "_OK",
    "_PERSON_EDITABLE_FIELDS",
    "_SEP",
    "_SUBTABS",
    "_TAB_ACTIVE",
    "_TAB_INACTIVE",
    "_VALID_ROLES",
    "_WARN",
    "AdapterSectionProjection",
    "AdapterStatus",
    "AdapterTab",
    "GuidedStep",
    "Subtab",
    "_normal_style",
    "classify_adapter_status",
    "get_allowed_values_for_field",
    "project_adapter_sections",
]
