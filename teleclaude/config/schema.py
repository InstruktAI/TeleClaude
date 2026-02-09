from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobWhenConfig(BaseModel):
    every: Optional[str] = None  # e.g. "10m", "2h", "1d"
    at: Optional[Union[str, List[str]]] = None  # "HH:MM" or list of times
    weekdays: List[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = []

    @field_validator("every")
    @classmethod
    def validate_every_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate duration format and enforce minimum of 1 minute."""
        if v is None:
            return v
        import re

        match = re.match(r"^(\d+)([mhd])$", v)
        if not match:
            raise ValueError(
                f"Invalid duration format: {v}. Expected format: <number><m|h|d> (e.g., '10m', '2h', '1d')"
            )
        value_int = int(match.group(1))
        if value_int < 1:
            raise ValueError(f"Duration must be at least 1 minute, got: {v}")
        return v

    @model_validator(mode="after")
    def validate_mode(self) -> "JobWhenConfig":
        # exactly one mode
        if bool(self.every) == bool(self.at):
            raise ValueError("Specify exactly one of 'every' or 'at'")
        # weekdays only with at
        if self.weekdays and not self.at:
            raise ValueError("'weekdays' requires 'at'")
        return self


class JobScheduleConfig(BaseModel):
    # New human-friendly scheduling contract
    when: Optional[JobWhenConfig] = None
    # Legacy compatibility during migration
    schedule: Optional[Literal["hourly", "daily", "weekly", "monthly"]] = None
    preferred_hour: int = Field(default=6, ge=0, le=23)
    preferred_weekday: int = Field(default=0, ge=0, le=6)
    preferred_day: int = Field(default=1, ge=1, le=31)

    # Execution config
    type: Optional[str] = None
    script: Optional[str] = None
    job: Optional[str] = None
    agent: Optional[str] = "claude"
    thinking_mode: Optional[str] = "fast"
    message: Optional[str] = None


class BusinessConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    domains: Dict[str, str] = {}


class GitConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    checkout_root: Optional[str] = None


class PersonEntry(BaseModel):
    name: str
    email: str
    username: Optional[str] = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"


class OpsEntry(BaseModel):
    username: str


class TelegramCreds(BaseModel):
    user_name: str
    user_id: int


class CredsConfig(BaseModel):
    telegram: Optional[TelegramCreds] = None


class NotificationsConfig(BaseModel):
    telegram: bool = False


class SubscriptionsConfig(BaseModel):
    youtube: Optional[str] = None


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    project_name: Optional[str] = None
    business: BusinessConfig = BusinessConfig()
    jobs: Dict[str, JobScheduleConfig] = {}
    git: GitConfig = GitConfig()

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        disallowed = {"people", "ops", "creds", "notifications", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at project level: {', '.join(present)}")
        return data


class GlobalConfig(ProjectConfig):
    people: List[PersonEntry] = []
    ops: List[OpsEntry] = []
    subscriptions: SubscriptionsConfig = SubscriptionsConfig()
    interests: List[str] = []

    @field_validator("interests", mode="before")
    @classmethod
    def parse_interests(cls, v: Any) -> Any:
        if isinstance(v, dict) and "tags" in v:
            return v["tags"]
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        # Global level allows more, but we might want to override the ProjectConfig one
        # to NOT reject people/ops if we ever decide to use them differently.
        # But GlobalConfig INHERITS ProjectConfig, so it will inherit its validator.
        # We need to ensure GlobalConfig allows people/ops.
        if not isinstance(data, dict):
            return data
        disallowed = {"creds", "notifications", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at global level: {', '.join(present)}")
        return data


class PersonConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    creds: CredsConfig = CredsConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    subscriptions: SubscriptionsConfig = SubscriptionsConfig()
    interests: List[str] = []

    @field_validator("interests", mode="before")
    @classmethod
    def parse_interests(cls, v: Any) -> Any:
        if isinstance(v, dict) and "tags" in v:
            return v["tags"]
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        disallowed = {"people", "ops", "business", "timezone"}
        present = disallowed.intersection(data.keys())
        if present:
            raise ValueError(f"Keys not allowed at per-person level: {', '.join(present)}")
        return data
