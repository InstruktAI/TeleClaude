"""Configuration schema models for TeleClaude."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from teleclaude.config.tiers import Tier
from teleclaude.constants import CHECKPOINT_BASE_ACTIONS
from teleclaude.events.domain_config import DomainsConfig
from teleclaude.slug import validate_slug


def normalize_env_allow_list(value: list[str]) -> list[str]:
    """Validate and de-duplicate agent-session environment variable names."""
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
    agent: str | None = None
    thinking_mode: str | None = "fast"
    message: str | None = None
    timeout: int | None = None


PUBLISHES_TRIGGER_MAX_LENGTH: Final = 200


class PublishesEntry(BaseModel):
    """A published domain and its required always-on activation trigger.

    With domain-resident triggered procedures scoped out of the always-on
    global catalog, this trigger is a published domain's only always-on
    tripwire, so both fields are required — a domain must never be
    deliverable undiscoverable.
    """

    model_config = ConfigDict(extra="allow")
    slug: str = Field(min_length=1)
    trigger: str

    @field_validator("trigger")
    @classmethod
    def validate_trigger(cls, v: str) -> str:
        """Reject blank, multiline, or over-length triggers before they reach agent output."""
        if "\n" in v or "\r" in v:
            raise ValueError("PublishesEntry.trigger must be single-line")
        stripped = v.strip()
        if not stripped:
            raise ValueError("PublishesEntry.trigger must be non-empty")
        if len(stripped) > PUBLISHES_TRIGGER_MAX_LENGTH:
            raise ValueError(f"PublishesEntry.trigger must be at most {PUBLISHES_TRIGGER_MAX_LENGTH} characters")
        return stripped


class BusinessConfig(BaseModel):
    """Business domain configuration."""

    model_config = ConfigDict(extra="allow")
    # Domains this project owns and contributes global snippets to, each with its
    # required always-on activation trigger. The union of every registered
    # project's `publishes` slugs is the set of valid domains; each domain has
    # exactly one owning publisher, enforced structurally at sync.
    publishes: list[PublishesEntry] = []


ProficiencyLevel = Literal["novice", "intermediate", "advanced", "expert"]
OUTPUT_VISIBILITY_MOBILE: Final = "mobile"
OUTPUT_VISIBILITY_WEB: Final = "web"
OUTPUT_VISIBILITY_BOTH: Final = "both"
OUTPUT_VISIBILITY_OFF: Final = "off"
OutputVisibilityValue = Literal["mobile", "web", "both", "off"]


class PersonEntry(BaseModel):
    """Person identity and role configuration."""

    model_config = ConfigDict(extra="allow")
    name: str
    email: str = Field(min_length=1)
    slug: str | None = None
    username: str | None = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"
    preferences: str | None = None  # Plain-text user preferences
    expertise: dict[str, ProficiencyLevel] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Normalize and reject empty person email values."""
        value = v.strip()
        if not value:
            raise ValueError("Person email must be non-empty")
        return value

    @field_validator("slug")
    @classmethod
    def validate_person_slug(cls, value: str | None) -> str | None:
        """Enforce slug format when the field is set.

        Empty/missing values normalize to ``None`` so pre-slug configs still
        load; slug migration fills the value. Mirrors ``validate_project_slug``.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        validate_slug(stripped)
        return stripped


class OutputVisibilitySettings(BaseModel):
    """Per-person visibility preferences for projected output categories."""

    model_config = ConfigDict(extra="allow")
    system_messages: OutputVisibilityValue | None = None
    tool_calls: OutputVisibilityValue | None = None

    @field_validator("system_messages", "tool_calls", mode="before")
    @classmethod
    def normalize_yaml_off(cls, value: Any) -> Any:
        """Normalize YAML 1.1's unquoted `off` boolean to the explicit off value."""
        if value is False:
            return OUTPUT_VISIBILITY_OFF
        return value


class PersonSettings(BaseModel):
    """Per-person settings container."""

    model_config = ConfigDict(extra="allow")
    output_visibility: OutputVisibilitySettings = OutputVisibilitySettings()


class PersonChipColorPair(BaseModel):
    """A theme-split color pair: one value for light mode, one for dark."""

    model_config = ConfigDict(extra="allow")
    light: str | None = None
    dark: str | None = None


class PersonChipColor(BaseModel):
    """Per-person chip color: a background and a text color, each theme-split.

    Every leaf is independently optional and defaults to ``None``. ``None`` is
    the renderer-default signal, not a stored color — the chip renderer fills it
    from the theme for the active mode. The nested pairs default to empty
    instances so the whole block can be instantiated as an empty tree and a
    single leaf can be set without pre-populating its siblings.
    """

    model_config = ConfigDict(extra="allow")
    background: PersonChipColorPair = PersonChipColorPair()
    text: PersonChipColorPair = PersonChipColorPair()


class MessagingChannel(StrEnum):
    """Named delivery channel vocabulary for person-addressed messaging routing."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


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


class CheckpointActionConfig(BaseModel):
    """A project-declared checkpoint action (verb) overlaid on the base registry."""

    model_config = ConfigDict(extra="allow")
    run: str = Field(min_length=1)
    evidence: list[str] = []
    main_only: bool = False
    precedence: int = 0
    evidence_must_follow_last_mutation: bool = False


class CheckpointScopeConfig(BaseModel):
    """A glob scope: ``include`` minus ``exclude``, re-added by ``override``."""

    model_config = ConfigDict(extra="allow")
    include: list[str] = []
    exclude: list[str] = []
    override: list[str] = []


class CheckpointBindingConfig(BaseModel):
    """Maps a scope to the action ids a matching changed file owes."""

    model_config = ConfigDict(extra="allow")
    scope: CheckpointScopeConfig = CheckpointScopeConfig()
    actions: list[str] = []


class CheckpointCodeConfig(BaseModel):
    """The conventional ``code`` kind: a scope onto which base ``test`` / ``log-check`` attach."""

    model_config = ConfigDict(extra="allow")
    scope: CheckpointScopeConfig = CheckpointScopeConfig()


class CheckpointExtraActionsConfig(BaseModel):
    """Optional extra actions appended atop a conventional base binding (``docs`` / ``agents``)."""

    model_config = ConfigDict(extra="allow")
    actions: list[str] = []


class CheckpointConfig(BaseModel):
    """Project checkpoint maintenance overlay merged atop the platform-universal base.

    Authored at analyze-time by intelligence (``telec projects analyze``) per
    ``project/procedure/checkpoint-overlay-projection``; consumed structurally by
    the checkpoint engine. An unreadable overlay degrades to base-only (fail-open).
    """

    model_config = ConfigDict(extra="allow")
    actions: dict[str, CheckpointActionConfig] = {}
    code: CheckpointCodeConfig | None = None
    bindings: list[CheckpointBindingConfig] = []
    docs: CheckpointExtraActionsConfig | None = None
    agents: CheckpointExtraActionsConfig | None = None

    @model_validator(mode="after")
    def validate_action_references(self) -> CheckpointConfig:
        """Every referenced action id must resolve to the base registry or a declared action.

        The runtime silently drops unknown action ids (``run_heuristics`` filters to
        the merged registry), so an unresolved reference would validate while the
        declared maintenance never surfaces. Reject it at the boundary instead, and
        reject a binding/extra block that references no action at all.
        """
        valid_ids = set(CHECKPOINT_BASE_ACTIONS) | set(self.actions)

        def _check(action_ids: list[str], where: str) -> None:
            if not action_ids:
                raise ValueError(f"checkpoint.{where} declares no actions")
            unknown = [action_id for action_id in action_ids if action_id not in valid_ids]
            if unknown:
                raise ValueError(
                    f"checkpoint.{where} references unknown action id(s): {', '.join(unknown)}; "
                    f"declare them under checkpoint.actions or reference a base action "
                    f"({', '.join(sorted(valid_ids))})"
                )

        for index, binding in enumerate(self.bindings):
            _check(binding.actions, f"bindings[{index}].actions")
        if self.docs is not None:
            _check(self.docs.actions, "docs.actions")
        if self.agents is not None:
            _check(self.agents.actions, "agents.actions")
        return self


class CapabilityConfig(BaseModel):
    """Subscription state for one project capability."""

    model_config = ConfigDict(extra="allow")
    enabled: bool = True


class ProjectConfig(BaseModel):
    """Project-level configuration: per-project ``teleclaude.yml`` overlay.

    This is the project-scoped overlay, not the machine runtime config — the
    public/editable machine surface is declared by the per-field ``tier`` markers
    on ``TeleclaudeConfig`` (``project/policy/config-public-surface``). Keys that
    belong machine-wide (the release channel, the workflow control plane) live on
    the machine config, not here.
    """

    model_config = ConfigDict(extra="allow")
    project_slug: str | None = None
    project_name: str | None = None
    description: str | None = None
    company: str | None = None
    env_allow_list: list[str] = []
    frontend_root: str | None = None
    business: BusinessConfig = BusinessConfig()
    hooks: HooksConfig = HooksConfig()
    jobs: dict[str, JobScheduleConfig] = {}
    channel_subscriptions: list[ChannelSubscription] = []
    checkpoint: CheckpointConfig | None = None
    code: CapabilityConfig = CapabilityConfig()
    docs: CapabilityConfig = CapabilityConfig()
    agents: CapabilityConfig = CapabilityConfig()

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

    @field_validator("company")
    @classmethod
    def validate_company_membership(cls, value: str | None) -> str | None:
        """Enforce kebab-case slug format on the project's company membership.

        Empty/missing values normalize to ``None`` — a project under no company
        umbrella is valid. A malformed slug is rejected rather than silently
        resolving to another company's context.
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
        return normalize_env_allow_list(value)

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        """Block keys that belong at other config levels."""
        if not isinstance(data, dict):
            return data
        disallowed = {"people", "ops", "creds", "notifications", "timezone", "workflow"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at project level: {', '.join(present)}")
        return data


class GlobalConfig(BaseModel):
    """Global-level configuration: the cross-project overlay (people, interests, overlay roots).

    Like ``ProjectConfig``, this is an overlay, not the machine runtime config; the
    public/editable machine surface is the per-field ``tier`` markers on
    ``TeleclaudeConfig`` (``project/policy/config-public-surface``). ``checkout_root``
    is the surviving git overlay key, marked ``internal`` — not human-edited in the
    wizard.
    """

    model_config = ConfigDict(extra="allow")
    env_allow_list: list[str] = []
    people: list[PersonEntry] = []
    subscriptions: list[SubscriptionEntry] = []
    interests: list[str] = []
    event_domains: DomainsConfig | None = None
    checkout_root: str | None = Field(default=None, json_schema_extra={"tier": Tier.INTERNAL})

    @field_validator("env_allow_list")
    @classmethod
    def validate_env_allow_list(cls, value: list[str]) -> list[str]:
        """Validate agent-session environment variable names."""
        return normalize_env_allow_list(value)

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
    subscriptions: list[SubscriptionEntry] = Field(default_factory=list, json_schema_extra={"tier": Tier.INTERNAL})
    interests: list[str] = []
    companies: list[str] = []
    settings: PersonSettings = PersonSettings()
    color: PersonChipColor | None = None
    preferred_channel: MessagingChannel | None = None

    @field_validator("interests", mode="before")
    @classmethod
    def parse_interests(cls, v: Any) -> Any:
        """Normalize legacy dict-based interests to list."""
        if isinstance(v, dict) and "tags" in v:
            return v["tags"]
        return v

    @field_validator("companies")
    @classmethod
    def validate_companies(cls, value: list[str]) -> list[str]:
        """Validate and de-duplicate the person's company-membership slugs.

        Many-to-many identity record: one person may work for several companies.
        Each entry is a kebab-case company slug; a malformed entry is rejected.
        """
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            validate_slug(stripped)
            if stripped in seen:
                continue
            seen.add(stripped)
            result.append(stripped)
        return result

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


class CompanyConfig(BaseModel):
    """Company-tier configuration: per-company ``teleclaude.yml`` overlay.

    Folder-discovered under ``~/.teleclaude/companies/<slug>/`` (the
    ``COMPANIES_ROOT`` tree) — the company-scoped twin of the per-person tier.
    Composed into the effective config alongside ``project`` (not workspace-type
    keyed): resolved from the active project's ``company`` membership. ERP is the
    system of record; every real company detail resolves through ``erp_id`` and is
    never duplicated here — the profile is thin context-scaffolding. ``extra=allow``
    for additive growth.
    """

    model_config = ConfigDict(extra="allow")
    name: str | None = None
    slug: str | None = None
    git: str | None = None
    description: str | None = None
    erp_id: str | None = None
    owner: str | None = None

    @field_validator("slug", "owner")
    @classmethod
    def validate_company_slugs(cls, value: str | None) -> str | None:
        """Enforce slug format on the company id and its ``PersonConfig.slug`` owner.

        Empty/missing values normalize to ``None`` so partially-authored profiles
        still load; a malformed slug is rejected at the model boundary.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        validate_slug(stripped)
        return stripped


@dataclass(frozen=True)
class AppConfig:
    """Composed application config — global always present; project, person, and company optional.

    ``company`` is resolved from the active project's ``company`` membership and
    composes alongside ``project`` (both present at once), unlike ``project`` and
    ``person`` which are mutually exclusive by workspace type.
    """

    global_: GlobalConfig
    project: ProjectConfig | None = None
    person: PersonConfig | None = None
    company: CompanyConfig | None = None
