from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobWhenConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
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

    @field_validator("at")
    @classmethod
    def validate_at_format(cls, v: Optional[Union[str, List[str]]]) -> Optional[Union[str, List[str]]]:
        """Validate HH:MM time format for 'at' values."""
        if v is None:
            return v
        import re

        def validate_time(time_str: str) -> None:
            match = re.match(r"^(\d{2}):(\d{2})$", time_str)
            if not match:
                raise ValueError(f"Invalid time format: {time_str}. Expected format: HH:MM (e.g., '09:00', '14:30')")
            hour, minute = int(match.group(1)), int(match.group(2))
            if not (0 <= hour <= 23):
                raise ValueError(f"Invalid hour in {time_str}: must be 00-23")
            if not (0 <= minute <= 59):
                raise ValueError(f"Invalid minute in {time_str}: must be 00-59")

        if isinstance(v, str):
            validate_time(v)
        else:  # List[str]
            for time_str in v:
                validate_time(time_str)
        return v

    @model_validator(mode="after")
    def validate_mode(self) -> "JobWhenConfig":
        # Exactly one scheduling mode is allowed.
        if bool(self.every) == bool(self.at):
            raise ValueError("Specify exactly one of 'every' or 'at'")
        # Weekday filtering is only valid for explicit wall-clock schedules.
        if self.weekdays and not self.at:
            raise ValueError("'weekdays' requires 'at'")
        return self


class JobScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    # Preferred scheduling contract.
    when: Optional[JobWhenConfig] = None
    # Legacy schedule fields remain supported as a fallback.
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
    timeout: Optional[int] = None


class BusinessConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    domains: Dict[str, str] = {}


class GitConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    checkout_root: Optional[str] = None


class PersonEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    email: str
    username: Optional[str] = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"


class OpsEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    username: str


class TelegramCreds(BaseModel):
    model_config = ConfigDict(extra="allow")
    user_name: str
    user_id: int


class CredsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    telegram: Optional[TelegramCreds] = None


class NotificationsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    telegram_chat_id: str | None = None
    telegram: bool = False
    channels: list[str] = []


class SubscriptionsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
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
        # Override project-level restrictions to allow global-only keys.
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
