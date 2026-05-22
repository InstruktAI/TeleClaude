"""Configuration schema models for TeleClaude."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from teleclaude.events.domain_config import DomainsConfig
from teleclaude.slug import validate_slug


class AgentDispatchConfig(BaseModel):
    """Per-agent dispatch configuration."""

    model_config = ConfigDict(extra="allow")
    enabled: bool = True


class JobWhenConfig(BaseModel):
    """Job scheduling time configuration."""

    model_config = ConfigDict(extra="allow")
    every: str | None = None  # e.g. "10m", "2h", "1d"
    at: str | list[str] | None = None  # "HH:MM" or list of times
    weekdays: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = []

    @field_validator("every")
    @classmethod
    def validate_every_format(cls, v: str | None) -> str | None:
        """Validate duration format and enforce minimum of 1 minute."""
        if v is None:
            return v
        match = re.match(r"^(\d+)([mhd])$", v)
        if not match:
            raise ValueError(
                f"Invalid duration format: {v}. Expected format: <number><m|h|d> (e.g., '10m', '2h', '1d')"
            )
        value_int = int(match.group(1))
        if value_int < 1:
            raise ValueError(f"Duration must be at least 1 minute, got: {v}")
        return v

    @field_validator("at")
    @classmethod
    def validate_at_format(cls, v: str | list[str] | None) -> str | list[str] | None:
        """Validate HH:MM time format for 'at' values."""
        if v is None:
            return v

        def validate_time(time_str: str) -> None:
            match = re.match(r"^(\d{2}):(\d{2})$", time_str)
            if not match:
                raise ValueError(f"Invalid time format: {time_str}. Expected format: HH:MM (e.g., '09:00', '14:30')")
            hour, minute = int(match.group(1)), int(match.group(2))
            if not 0 <= hour <= 23:
                raise ValueError(f"Invalid hour in {time_str}: must be 00-23")
            if not 0 <= minute <= 59:
                raise ValueError(f"Invalid minute in {time_str}: must be 00-59")

        if isinstance(v, str):
            validate_time(v)
        else:  # List[str]
            for time_str in v:
                validate_time(time_str)
        return v

    @model_validator(mode="after")
    def validate_mode(self) -> JobWhenConfig:
        """Ensure exactly one scheduling mode is specified."""
        # Exactly one scheduling mode is allowed.
        if bool(self.every) == bool(self.at):
            raise ValueError("Specify exactly one of 'every' or 'at'")
        # Weekday filtering is only valid for explicit wall-clock schedules.
        if self.weekdays and not self.at:
            raise ValueError("'weekdays' requires 'at'")
        return self


class JobScheduleConfig(BaseModel):
    """Job scheduling and execution configuration."""

    model_config = ConfigDict(extra="allow")
    category: Literal["subscription", "system"] = "subscription"
    # Preferred scheduling contract.
    when: JobWhenConfig | None = None
    # Legacy schedule fields remain supported as a fallback.
    schedule: Literal["hourly", "daily", "weekly", "monthly"] | None = None
    preferred_hour: int = Field(default=6, ge=0, le=23)
    preferred_weekday: int = Field(default=0, ge=0, le=6)
    preferred_day: int = Field(default=1, ge=1, le=31)

    # Execution config
    type: str | None = None
    script: str | None = None
    job: str | None = None
    agent: str | None = "claude"
    thinking_mode: str | None = "fast"
    message: str | None = None
    timeout: int | None = None


class BusinessConfig(BaseModel):
    """Business domain configuration."""

    model_config = ConfigDict(extra="allow")
    domains: dict[str, str] = {}


class GitConfig(BaseModel):
    """Git repository configuration."""

    model_config = ConfigDict(extra="allow")


class IntegratorCutoverConfig(BaseModel):
    """Integrator cutover feature flags."""

    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    parity_evidence_accepted: bool = False
    rollback_on_incomplete_parity: bool = True

    @model_validator(mode="after")
    def validate_cutover_enablement(self) -> IntegratorCutoverConfig:
        """Require parity evidence before enabling cutover."""
        if self.enabled and not self.parity_evidence_accepted:
            raise ValueError(
                "integrator.cutover.enabled requires parity_evidence_accepted=true; "
                "disable cutover to rollback until parity is accepted"
            )
        return self


class IntegratorConfig(BaseModel):
    """Integrator subsystem configuration."""

    model_config = ConfigDict(extra="allow")
    cutover: IntegratorCutoverConfig = IntegratorCutoverConfig()


ProficiencyLevel = Literal["novice", "intermediate", "advanced", "expert"]


class PersonEntry(BaseModel):
    """Person identity and role configuration."""

    model_config = ConfigDict(extra="allow")
    name: str
    email: str = Field(min_length=1)
    username: str | None = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"
    expertise: dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Normalize and reject empty person email values."""
        value = v.strip()
        if not value:
            raise ValueError("Person email must be non-empty")
        return value


class TelegramCreds(BaseModel):
    """Telegram platform credentials."""

    model_config = ConfigDict(extra="allow")
    user_name: str
    user_id: int
    chat_id: str | None = None


class DiscordCreds(BaseModel):
    """Discord platform credentials."""

    model_config = ConfigDict(extra="allow")
    user_id: str  # Discord user IDs are snowflakes (strings)
    nick: str | None = None


class WhatsAppCreds(BaseModel):
    """WhatsApp platform credentials."""

    model_config = ConfigDict(extra="allow")
    phone_number: str


class CredsConfig(BaseModel):
    """Multi-platform credential container."""

    model_config = ConfigDict(extra="allow")
    telegram: TelegramCreds | None = None
    discord: DiscordCreds | None = None
    whatsapp: WhatsAppCreds | None = None


class SubscriptionNotification(BaseModel):
    """Notification channel preference for a subscription."""

    model_config = ConfigDict(extra="allow")
    preferred_channel: Literal["telegram", "discord", "whatsapp", "email"] = "telegram"
    email: str | None = None


class Subscription(BaseModel):
    """Base subscription model."""

    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    notification: SubscriptionNotification = SubscriptionNotification()


class JobSubscription(Subscription):
    """Job-triggered subscription."""

    type: Literal["job"] = "job"
    job: str
    when: JobWhenConfig | None = None


class YoutubeSubscription(Subscription):
    """YouTube channel subscription."""

    type: Literal["youtube"] = "youtube"
    source: str
    tags: list[str] = []


SubscriptionEntry = Annotated[
    JobSubscription | YoutubeSubscription,
    Field(discriminator="type"),
]


class InboundSourceConfig(BaseModel):
    """Inbound webhook source configuration."""

    model_config = ConfigDict(extra="allow")
    path: str | None = None
    verify_token: str | None = None
    secret: str | None = None
    normalizer: str | None = None


class SubscriptionContractConfig(BaseModel):
    """Subscription matching contract."""

    model_config = ConfigDict(extra="allow")
    source: dict[str, Any] | None = None
    type: dict[str, Any] | None = None
    # Additional property criteria as extra fields


class SubscriptionTargetConfig(BaseModel):
    """Subscription delivery target."""

    model_config = ConfigDict(extra="allow")
    handler: str | None = None
    url: str | None = None
    secret: str | None = None


class SubscriptionConfig(BaseModel):
    """Hook subscription configuration."""

    model_config = ConfigDict(extra="allow")
    id: str
    contract: dict[str, Any] = {}  # guard: loose-dict - Config YAML contract is unstructured
    target: dict[str, Any] = {}  # guard: loose-dict - Config YAML target is unstructured


class ChannelSubscription(BaseModel):
    """A subscription that routes messages from a Redis Stream channel to a target."""

    model_config = ConfigDict(extra="allow")
    channel: str
    filter: dict[str, Any] | None = None  # guard: loose-dict - Subscription filter is intentionally unstructured
    target: dict[str, Any] = {}  # guard: loose-dict - Subscription target (notification or project+command)


class HooksConfig(BaseModel):
    """Hooks and subscriptions configuration."""

    model_config = ConfigDict(extra="allow")
    inbound: dict[str, InboundSourceConfig] = {}
    subscriptions: list[SubscriptionConfig] = []


class DeploymentConfig(BaseModel):
    """Release channel and version pinning."""

    model_config = ConfigDict(extra="allow")
    channel: Literal["alpha", "beta", "stable"] = "alpha"
    pinned_minor: str = ""

    @model_validator(mode="after")
    def validate_stable_requires_pinned_minor(self) -> DeploymentConfig:
        """Require pinned_minor for stable channel."""
        if self.channel == "stable" and not self.pinned_minor:
            raise ValueError("pinned_minor is required and must be non-empty when channel=stable")
        return self


class ProjectConfig(BaseModel):
    """Project-level configuration."""

    model_config = ConfigDict(extra="allow")
    project_slug: str | None = None
    project_name: str | None = None
    description: str | None = None
    language: str | None = None
    languages: list[str] = []
    env_allow_list: list[str] = []
    frontend_root: str | None = None
    business: BusinessConfig = BusinessConfig()
    hooks: HooksConfig = HooksConfig()
    jobs: dict[str, JobScheduleConfig] = {}
    git: GitConfig = GitConfig()
    integrator: IntegratorConfig = IntegratorConfig()
    channel_subscriptions: list[ChannelSubscription] = []
    deployment: DeploymentConfig = DeploymentConfig()

    @field_validator("project_slug")
    @classmethod
    def validate_project_slug(cls, value: str | None) -> str | None:
        """Enforce slug format when the field is set.

        Empty/missing values are accepted here so legacy configs still load;
        ``telec projects init`` fills the value during registration.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        validate_slug(stripped)
        return stripped

    @field_validator("env_allow_list")
    @classmethod
    def validate_env_allow_list(cls, value: list[str]) -> list[str]:
        """Validate agent-session environment variable names."""
        valid_name = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            name = item.strip()
            if not valid_name.fullmatch(name):
                raise ValueError(f"Invalid environment variable name in env_allow_list: {item}")
            if name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        """Block keys that belong at other config levels."""
        if not isinstance(data, dict):
            return data
        disallowed = {"people", "ops", "creds", "notifications", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at project level: {', '.join(present)}")
        return data


class GlobalConfig(BaseModel):
    """Global-level configuration."""

    model_config = ConfigDict(extra="allow")
    people: list[PersonEntry] = []
    subscriptions: list[SubscriptionEntry] = []
    interests: list[str] = []
    event_domains: DomainsConfig | None = None
    checkout_root: str | None = None

    @field_validator("interests", mode="before")
    @classmethod
    def parse_interests(cls, v: Any) -> Any:
        """Normalize legacy dict-based interests to list."""
        if isinstance(v, dict) and "tags" in v:
            return v["tags"]
        return v

    @model_validator(mode="before")
    @classmethod
    def migrate_git_checkout_root(cls, data: Any) -> Any:
        """Migrate git.checkout_root from legacy YAML path to top-level checkout_root."""
        if not isinstance(data, dict):
            return data
        git = data.get("git")
        if isinstance(git, dict) and "checkout_root" in git and "checkout_root" not in data:
            data = dict(data)
            data["checkout_root"] = git["checkout_root"]
        return data

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        """Block keys that belong at per-person config level."""
        if not isinstance(data, dict):
            return data
        disallowed = {"creds", "notifications", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at global level: {', '.join(present)}")
        return data


class PersonConfig(BaseModel):
    """Per-person configuration."""

    model_config = ConfigDict(extra="allow")
    creds: CredsConfig = CredsConfig()
    subscriptions: list[SubscriptionEntry] = []
    interests: list[str] = []
    invite_token: str | None = None

    @field_validator("interests", mode="before")
    @classmethod
    def parse_interests(cls, v: Any) -> Any:
        """Normalize legacy dict-based interests to list."""
        if isinstance(v, dict) and "tags" in v:
            return v["tags"]
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        """Block keys that belong at other config levels."""
        if not isinstance(data, dict):
            return data
        disallowed = {"people", "ops", "business", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at per-person level: {', '.join(present)}")
        return data


@dataclass(frozen=True)
class AppConfig:
    """Composed application config — global always present; project and person optional."""

    global_: GlobalConfig
    project: ProjectConfig | None = None
    person: PersonConfig | None = None
