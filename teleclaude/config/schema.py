"""Configuration schema models for TeleClaude."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self

from pydantic import ConfigDict, Field, ModelWrapValidatorHandler, ValidationInfo, field_validator, model_validator

from teleclaude.agent_registry import AgentName
from teleclaude.closed_model import SENSITIVE, ClosedModel
from teleclaude.config.checkpoint_schema import CheckpointConfig
from teleclaude.config.field_constraints import (
    RequiredWhen,
    Requires,
    append_constraint_rules,
    declared_constraints,
    refuse_unmet_requirements,
    refuse_violations,
)
from teleclaude.config.github_schema import GlobalGitHubConfig, PersonGitHubConfig
from teleclaude.config.identity_schema import CompanyMember, PersonEntry
from teleclaude.config.project_models import CapabilityConfig, CiConfig, TodoStoreConfig
from teleclaude.config.tiers import Tier
from teleclaude.project_manifest import ConfigKind as ConfigKind
from teleclaude.slug import SLUG_PATTERN, validate_slug
from teleclaude.snippet_scope import RESERVED_HOME_IDENTITY_PREFIXES

CURRENT_SCHEMA_VERSION = 31
_BLANK_INBOUND_SECRET_ERROR = "An inbound source requires a non-blank secret"
_BLANK_INBOUND_VERIFY_TOKEN_ERROR = "The WhatsApp inbound source requires a non-blank verify_token"


def normalize_env_allow_list(value: list[str]) -> list[str]:
    """Validate and de-duplicate agent-session environment variable names."""
    valid_name = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = item.strip()
        if not valid_name.fullmatch(name):
            raise ValueError("Invalid environment variable name in env_allow_list")
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


class AgentDispatchConfig(ClosedModel):
    """Per-agent dispatch configuration."""

    enabled: bool = True


class JobWhenConfig(ClosedModel):
    """Job scheduling time configuration."""

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
            raise ValueError("Invalid duration format. Expected format: <number><m|h|d> (e.g., '10m', '2h', '1d')")
        value_int = int(match.group(1))
        if value_int < 1:
            raise ValueError("Duration must be at least 1 minute")
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
                raise ValueError("Invalid time format. Expected format: HH:MM (e.g., '09:00', '14:30')")
            hour, minute = int(match.group(1)), int(match.group(2))
            if not 0 <= hour <= 23:
                raise ValueError("Invalid hour: must be 00-23")
            if not 0 <= minute <= 59:
                raise ValueError("Invalid minute: must be 00-59")

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


class JobCategory(StrEnum):
    """The scheduling relationship a job declaration has to a project."""

    SUBSCRIPTION = "subscription"
    SYSTEM = "system"


class JobType(StrEnum):
    """The execution form projected for a job declaration."""

    AGENT = "agent"
    SCRIPT = "script"


class JobScheduleConfig(ClosedModel):
    """One declarative scheduled job or subscription override."""

    name: str
    category: JobCategory = JobCategory.SUBSCRIPTION
    enabled: bool = True
    when: JobWhenConfig | None = None
    script: str | None = None
    job: str | None = None
    agent: list[AgentName] | None = None
    thinking_mode: str | None = None
    timeout: int | None = None

    @field_validator("name")
    @classmethod
    def validate_job_name(cls, value: str) -> str:
        """Require the declared job identity in its exact kebab-case form."""
        if not SLUG_PATTERN.fullmatch(value):
            raise ValueError(_JOB_NAME_INVALID_ERROR)
        return value

    @field_validator("agent", mode="before")
    @classmethod
    def normalize_agents(cls, value: object) -> object:
        """Normalize declared candidate aliases to the registry vocabulary."""
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("agent must be a YAML list")
        return [AgentName.from_str(item) if isinstance(item, str) else item for item in value]

    @model_validator(mode="after")
    def require_one_execution_target(self) -> JobScheduleConfig:
        """Reject declarations that carry both execution targets."""
        script = self.script.strip() if self.script else ""
        procedure = self.job.strip() if self.job else ""
        if script and procedure:
            raise ValueError(_JOB_BOTH_EXECUTION_TARGETS_ERROR.format(name=self.name))
        return self


_JOB_NAME_INVALID_ERROR: Final = "job name must be lowercase kebab-case"
_JOB_BOTH_EXECUTION_TARGETS_ERROR: Final = "job '{name}' carries both script and job execution pointers"
_JOB_DUPLICATE_NAME_ERROR: Final = "duplicate job name: {name}"
_PUBLISHED_JOB_TARGET_REQUIRED_ERROR: Final = "published job '{name}' requires exactly one execution pointer"


def _validate_job_tier(
    jobs: list[JobScheduleConfig], *, require_execution_target: bool = False
) -> list[JobScheduleConfig]:
    """Validate name uniqueness and the published tier's execution pointers."""
    names: set[str] = set()
    for declaration in jobs:
        if declaration.name in names:
            raise ValueError(_JOB_DUPLICATE_NAME_ERROR.format(name=declaration.name))
        names.add(declaration.name)
        if require_execution_target:
            pointers = (declaration.script, declaration.job)
            if sum(bool(pointer and pointer.strip()) for pointer in pointers) != 1:
                raise ValueError(_PUBLISHED_JOB_TARGET_REQUIRED_ERROR.format(name=declaration.name))
    return jobs


def is_agent_job(schedule: JobScheduleConfig) -> bool:
    """Return whether a declaration targets an agent procedure."""
    return bool(schedule.job and schedule.job.strip())


PUBLISHES_TRIGGER_MAX_LENGTH: Final = 200
#: The notification category, and publishing slug it reserves, for the platform's own events.
PLATFORM_EVENT_CATEGORY: Final = "teleclaude"
_RESERVED_IDENTITY_PREFIX_ERROR: Final = (
    "PublishesEntry.slug {slug!r} is a reserved snippet identity prefix and cannot name a domain"
)
_RESERVED_PLATFORM_CATEGORY_ERROR: Final = (
    "PublishesEntry.slug {slug!r} is reserved for the platform's own events and cannot name a domain"
)


class PublishesEntry(ClosedModel):
    """A published domain and its required always-on activation trigger.

    With domain-resident triggered procedures scoped out of the always-on
    global catalog, this trigger is a published domain's only always-on
    tripwire, so both fields are required — a domain must never be
    deliverable undiscoverable.
    """

    slug: str = Field(min_length=1)
    trigger: str

    @field_validator("slug")
    @classmethod
    def validate_slug_not_home_prefix(cls, v: str) -> str:
        """Reject domain slugs reserved by the snippet identity grammar."""
        if v.strip() in RESERVED_HOME_IDENTITY_PREFIXES:
            raise ValueError(_RESERVED_IDENTITY_PREFIX_ERROR.format(slug=v.strip()))
        if v.strip() == PLATFORM_EVENT_CATEGORY:
            raise ValueError(_RESERVED_PLATFORM_CATEGORY_ERROR.format(slug=v.strip()))
        return v

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


class BusinessConfig(ClosedModel):
    """Business domain configuration."""

    # Domains this project owns and contributes global snippets to, each with its
    # required always-on activation trigger. The union of every registered
    # project's `publishes` slugs is the set of valid domains; each domain has
    # exactly one owning publisher, enforced structurally at sync.
    publishes: list[PublishesEntry] = []


OUTPUT_VISIBILITY_MOBILE: Final = "mobile"
OUTPUT_VISIBILITY_FULL: Final = "full"
OUTPUT_VISIBILITY_BOTH: Final = "both"
OUTPUT_VISIBILITY_OFF: Final = "off"
OutputVisibilityValue = Literal["mobile", "full", "both", "off"]
_PROJECT_OWNER_CONFLICT = "Project configuration cannot declare both company and person owners"
_CI_REQUIRES_ERROR = "A ci block requires {keys}"
_CI_KEY_SEPARATOR = ", "
_CI_REQUIRED_REPOSITORY = "todos.repository"
_CI_REQUIRED_APP = "todos.app"
_CI_REQUIRED_GITHUB_SOURCE = "hooks.inbound.github"
# Only the ingress verifies inbound requests.
_INGRESS_FLAG: Final = "computer.is_ingress_node"


class MailConnector(StrEnum):
    """Connector vocabulary for mail accounts an assistant may invoke."""

    GOOGLE = "google"
    MICROSOFT = "microsoft"


class MailAccount(ClosedModel):
    """One declared mail account available to a person's assistant."""

    connector: MailConnector
    address: str = Field(min_length=1)


class OutputVisibilitySettings(ClosedModel):
    """Per-person visibility preferences for projected output categories."""

    system_messages: OutputVisibilityValue | None = None
    tool_calls: OutputVisibilityValue | None = None

    @field_validator("system_messages", "tool_calls", mode="before")
    @classmethod
    def normalize_yaml_off(cls, value: Any) -> Any:
        """Normalize YAML 1.1's unquoted `off` boolean to the explicit off value."""
        if value is False:
            return OUTPUT_VISIBILITY_OFF
        return value


class PersonSettings(ClosedModel):
    """Per-person settings container."""

    output_visibility: OutputVisibilitySettings = OutputVisibilitySettings()


class PersonChipColorPair(ClosedModel):
    """A theme-split color pair: one value for light mode, one for dark."""

    light: str | None = None
    dark: str | None = None


class PersonChipColor(ClosedModel):
    """Per-person chip color: a background and a text color, each theme-split.

    Every leaf is independently optional and defaults to ``None``. ``None`` is
    the renderer-default signal, not a stored color — the chip renderer fills it
    from the theme for the active mode. The nested pairs default to empty
    instances so the whole block can be instantiated as an empty tree and a
    single leaf can be set without pre-populating its siblings.
    """

    background: PersonChipColorPair = PersonChipColorPair()
    text: PersonChipColorPair = PersonChipColorPair()


class MessagingChannel(StrEnum):
    """Named delivery channel vocabulary for person-addressed messaging routing."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class TelegramCreds(ClosedModel):
    """Telegram platform credentials."""

    user_name: str
    user_id: int
    chat_id: str | None = None


class DiscordCreds(ClosedModel):
    """Discord platform credentials."""

    user_id: str  # Discord user IDs are snowflakes (strings)
    nick: str | None = None
    avatar_url: str | None = None
    voice_bot_token: Annotated[str | None, SENSITIVE] = None


class WhatsAppCreds(ClosedModel):
    """WhatsApp platform credentials."""

    phone_number: str


class CredsConfig(ClosedModel):
    """Multi-platform credential container."""

    telegram: TelegramCreds | None = None
    discord: DiscordCreds | None = None
    whatsapp: WhatsAppCreds | None = None


class SubscriptionNotification(ClosedModel):
    """Notification channel preference for a subscription."""

    preferred_channel: Literal["telegram", "discord", "whatsapp", "email"] = "telegram"
    email: str | None = None


class Subscription(ClosedModel):
    """Base subscription model."""

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


class SignedInboundSource(ClosedModel):
    """One inbound source whose requests are verified under the declaring home's secret.

    The secret is absent on a computer whose `.env` holds no value for its reference; only the
    ingress verifies requests, and it refuses a request it cannot verify.
    """

    secret: Annotated[str | None, SENSITIVE, RequiredWhen(_INGRESS_FLAG)] = None

    @field_validator("secret")
    @classmethod
    def require_nonblank_secret(cls, value: str | None) -> str | None:
        """Refuse a blank secret: a present secret must be usable for verification."""
        if value is not None and not value.strip():
            raise ValueError(_BLANK_INBOUND_SECRET_ERROR)
        return value


class WhatsAppInboundSource(SignedInboundSource):
    """The WhatsApp Cloud API source: Meta's signature secret and its subscription handshake token."""

    verify_token: Annotated[str | None, SENSITIVE, RequiredWhen(_INGRESS_FLAG)] = None

    @field_validator("verify_token")
    @classmethod
    def require_nonblank_verify_token(cls, value: str | None) -> str | None:
        """Refuse a blank handshake token."""
        if value is not None and not value.strip():
            raise ValueError(_BLANK_INBOUND_VERIFY_TOKEN_ERROR)
        return value


class NativeInboundSources(ClosedModel):
    """Inbound protocols a company or person home may declare."""

    native: SignedInboundSource | None = None


class ProjectInboundSources(NativeInboundSources):
    """Inbound protocols a project home may declare."""

    github: SignedInboundSource | None = None


class GlobalInboundSources(ClosedModel):
    """Inbound protocols the global configuration may declare."""

    whatsapp: WhatsAppInboundSource | None = None


class HooksConfig(ClosedModel):
    """A project's own inbound sources."""

    inbound: ProjectInboundSources = ProjectInboundSources()


class HomeHooksConfig(ClosedModel):
    """A company's or person's own inbound sources."""

    inbound: NativeInboundSources = NativeInboundSources()


class GlobalHooksConfig(ClosedModel):
    """The global configuration's inbound sources."""

    inbound: GlobalInboundSources = GlobalInboundSources()


class HelpDeskConfig(ClosedModel):
    """Whether a home keeps a help desk; an omitted block keeps none."""

    enabled: bool = False


class ProjectHelpDeskConfig(ClosedModel):
    """Whether a project keeps a help desk; its folder launches a confined agent, so the project subscribes `agents`."""

    enabled: Annotated[bool, Requires("agents.enabled", True)] = False


class TierDocument(ClosedModel):
    """The closed base of the tier documents, enforcing and publishing declared field constraints.

    A relationship declared on a field is checked after the document validates, refused at the
    requiring field with the declared message, and published as a conditional rule in the
    document's JSON Schema. A declaration that cannot be expressed identically everywhere fails
    when the document model is defined.
    """

    model_config = ConfigDict(json_schema_extra=append_constraint_rules)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        declared_constraints(cls)

    @model_validator(mode="wrap")
    @classmethod
    def _enforce_field_constraints(
        cls, data: object, handler: ModelWrapValidatorHandler[Self], info: ValidationInfo
    ) -> Self:
        instance = handler(data)
        refuse_violations(cls, instance)
        refuse_unmet_requirements(cls, info.context)
        return instance


class ProjectConfig(TierDocument):
    """Project-level configuration: per-project ``teleclaude.yml`` overlay.

    This is the project-scoped overlay, not the machine runtime config — the
    public/editable machine surface is declared by the per-field ``tier`` markers
    on ``TeleclaudeConfig`` (``local/projects/teleclaude/policy/config-public-surface``). Keys that
    belong machine-wide (the release channel, the workflow control plane) live on
    the machine config, not here.
    """

    kind: Literal[ConfigKind.PROJECT] = Field(json_schema_extra={"tier": Tier.INTERNAL})
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=0, json_schema_extra={"tier": Tier.INTERNAL})
    project_slug: str | None = None
    project_name: str | None = None
    description: str | None = None
    company: str | None = None
    person: str | None = None
    env_allow_list: list[str] = []
    frontend_root: str | None = None
    business: BusinessConfig = BusinessConfig()
    hooks: HooksConfig = HooksConfig()
    todos: TodoStoreConfig = TodoStoreConfig()
    jobs: list[JobScheduleConfig] = []
    checkpoint: CheckpointConfig | None = None
    code: CapabilityConfig = CapabilityConfig()
    docs: CapabilityConfig = CapabilityConfig()
    agents: CapabilityConfig = CapabilityConfig()
    help_desk: ProjectHelpDeskConfig = ProjectHelpDeskConfig()
    ci: CiConfig | None = None

    @field_validator("jobs")
    @classmethod
    def validate_jobs(cls, jobs: list[JobScheduleConfig]) -> list[JobScheduleConfig]:
        """Require unique names while allowing pointer-free subscriptions."""
        return _validate_job_tier(jobs)

    @field_validator("project_slug")
    @classmethod
    def validate_project_slug(cls, value: str | None) -> str | None:
        """Enforce slug format when the field is set.

        Empty/missing values are accepted here so legacy configs still load;
        project adoption (``telec config project adopt``) and creation fill the
        value during registration.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        validate_slug(stripped)
        return stripped

    @field_validator("company", "person")
    @classmethod
    def validate_project_owner(cls, value: str | None) -> str | None:
        """Enforce kebab-case slug format on a declared project owner.

        Empty/missing values normalize to ``None`` so ownerless projects remain
        valid. A malformed slug is rejected rather than silently resolving to a
        different owner.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        validate_slug(stripped)
        return stripped

    @model_validator(mode="after")
    def reject_multiple_owners(self) -> Self:
        """Reject a project declaration that names both ownership alternatives."""
        if self.company is not None and self.person is not None:
            raise ValueError(_PROJECT_OWNER_CONFLICT)
        return self

    @model_validator(mode="after")
    def require_ci_prerequisites(self) -> Self:
        """Refuse a ci block whose runs could not be read or filed: it needs the repository, the App and the GitHub source."""
        if self.ci is None:
            return self
        missing = [
            key
            for key, declared in (
                (_CI_REQUIRED_REPOSITORY, self.todos.repository is not None),
                (_CI_REQUIRED_APP, self.todos.app is not None),
                (_CI_REQUIRED_GITHUB_SOURCE, self.hooks.inbound.github is not None),
            )
            if not declared
        ]
        if missing:
            raise ValueError(_CI_REQUIRES_ERROR.format(keys=_CI_KEY_SEPARATOR.join(missing)))
        return self

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
        disallowed = {"people", "ops", "creds", "timezone", "workflow"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at project level: {', '.join(present)}")
        return data


class GlobalConfig(TierDocument):
    """Global-level configuration: the cross-project overlay (people, interests, overlay roots).

    Like ``ProjectConfig``, this is an overlay, not the machine runtime config; the
    public/editable machine surface is the per-field ``tier`` markers on
    ``TeleclaudeConfig`` (``local/projects/teleclaude/policy/config-public-surface``). ``checkout_root``
    is the surviving git overlay key, marked ``internal`` — not human-edited in the
    wizard.
    """

    kind: Literal[ConfigKind.GLOBAL] = Field(json_schema_extra={"tier": Tier.INTERNAL})
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=0, json_schema_extra={"tier": Tier.INTERNAL})
    env_allow_list: list[str] = []
    people: list[PersonEntry] = []
    jobs: list[JobScheduleConfig] = []
    subscriptions: list[SubscriptionEntry] = []
    interests: list[str] = []
    checkout_root: str | None = Field(default=None, json_schema_extra={"tier": Tier.INTERNAL})
    hooks: GlobalHooksConfig = GlobalHooksConfig()
    github: GlobalGitHubConfig = Field(default_factory=GlobalGitHubConfig)

    @field_validator("jobs")
    @classmethod
    def validate_jobs(cls, jobs: list[JobScheduleConfig]) -> list[JobScheduleConfig]:
        """Require unique names and one target for every published job."""
        return _validate_job_tier(jobs, require_execution_target=True)

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
    def reject_disallowed_keys(cls, data: Any) -> Any:
        """Block keys that belong at per-person config level."""
        if not isinstance(data, dict):
            return data
        disallowed = {"creds", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at global level: {', '.join(present)}")
        return data


class NotificationCategory(ClosedModel):
    """One category of a person's notification interests: a switch and type patterns.

    Patterns stay strings so one unusable entry never fails the person's document;
    ``teleclaude.config.notification_interests`` owns what a usable pattern is.
    """

    enabled: bool = True
    events: list[str] = Field(default_factory=list)


class PersonConfig(TierDocument):
    """Per-person configuration."""

    kind: Literal[ConfigKind.PERSON] = Field(json_schema_extra={"tier": Tier.INTERNAL})
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=0, json_schema_extra={"tier": Tier.INTERNAL})
    slug: str = Field(json_schema_extra={"tier": Tier.INTERNAL})
    name: str | None = None
    description: str | None = None
    creds: CredsConfig = CredsConfig()
    github: PersonGitHubConfig = Field(default_factory=PersonGitHubConfig)
    subscriptions: list[SubscriptionEntry] = Field(default_factory=list, json_schema_extra={"tier": Tier.INTERNAL})
    mail_accounts: list[MailAccount] = Field(default_factory=list, json_schema_extra={"tier": Tier.INTERNAL})
    interests: list[str] = []
    notifications: dict[str, NotificationCategory] = Field(default_factory=dict)
    settings: PersonSettings = PersonSettings()
    color: PersonChipColor | None = None
    preferred_channel: MessagingChannel | None = None
    hooks: HomeHooksConfig = HomeHooksConfig()

    @field_validator("slug")
    @classmethod
    def validate_person_claim(cls, value: str) -> str:
        """Validate the registered identity claim carried by this overlay."""
        stripped = value.strip()
        validate_slug(stripped)
        return stripped

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


class CompanyConfig(TierDocument):
    """Company-tier configuration: per-company ``teleclaude.yml`` overlay.

    Folder-discovered under ``~/.teleclaude/companies/<slug>/`` (the
    ``COMPANIES_ROOT`` tree) — the company-scoped twin of the per-person tier.
    Composed into the effective config alongside ``project`` (not workspace-type
    keyed): resolved from the active project's ``company`` membership. ERP is the
    system of record; every real company detail resolves through ``erp_id`` and is
    never duplicated here — the profile is thin context-scaffolding. File-backed
    overlays reject undeclared fields at their load boundary.
    """

    kind: Literal[ConfigKind.COMPANY] = Field(json_schema_extra={"tier": Tier.INTERNAL})
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION, ge=0, json_schema_extra={"tier": Tier.INTERNAL})
    name: str | None = None
    slug: str | None = None
    git: str | None = None
    description: str | None = None
    erp_id: str | None = None
    members: dict[str, CompanyMember] = Field(default_factory=dict)
    help_desk: HelpDeskConfig = HelpDeskConfig()
    hooks: HomeHooksConfig = HomeHooksConfig()

    @field_validator("slug")
    @classmethod
    def validate_company_slugs(cls, value: str | None) -> str | None:
        """Enforce slug format on the company id.

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

    @field_validator("members")
    @classmethod
    def validate_members(cls, value: dict[str, CompanyMember]) -> dict[str, CompanyMember]:
        """Validate every roster key as the slug of its declared person."""
        for person_slug in value:
            validate_slug(person_slug)
        return value


TIER_DOCUMENT_MODELS: Final[Mapping[ConfigKind, type[TierDocument]]] = {
    ConfigKind.GLOBAL: GlobalConfig,
    ConfigKind.PROJECT: ProjectConfig,
    ConfigKind.PERSON: PersonConfig,
    ConfigKind.COMPANY: CompanyConfig,
}
"""The tier document model of each configuration kind."""


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
