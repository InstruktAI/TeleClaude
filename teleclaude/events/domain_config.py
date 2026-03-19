"""Domain event processing configuration schema."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AutonomyLevel(str, Enum):
    """Execution autonomy levels for domain cartridges."""

    MANUAL = "manual"
    NOTIFY = "notify"
    AUTO_NOTIFY = "auto_notify"
    AUTONOMOUS = "autonomous"


class AutonomyMatrix(BaseModel):
    """Priority-ordered autonomy overrides for domains, cartridges, and events."""

    model_config = ConfigDict(extra="allow")

    global_default: AutonomyLevel = AutonomyLevel.NOTIFY
    by_domain: dict[str, AutonomyLevel] = Field(default_factory=dict)
    by_cartridge: dict[str, AutonomyLevel] = Field(default_factory=dict)  # key: "{domain}/{cartridge_id}"
    by_event_type: dict[str, AutonomyLevel] = Field(default_factory=dict)  # key: "{domain}/{event_type}"

    def resolve(self, domain: str, cartridge_id: str, event_type: str) -> AutonomyLevel:
        """Resolve autonomy level with priority: event_type > cartridge > domain > global."""
        event_key = f"{domain}/{event_type}"
        if event_key in self.by_event_type:
            return self.by_event_type[event_key]

        cartridge_key = f"{domain}/{cartridge_id}"
        if cartridge_key in self.by_cartridge:
            return self.by_cartridge[cartridge_key]

        if domain in self.by_domain:
            return self.by_domain[domain]

        return self.global_default


class DomainGuardianConfig(BaseModel):
    """Guardian agent settings used when a domain requires evaluation."""

    model_config = ConfigDict(extra="allow")

    agent: str = "claude"
    mode: str = "med"
    enabled: bool = True
    evaluation_prompt: str | None = None


class DomainConfig(BaseModel):
    """Configuration for a single domain-specific event pipeline."""

    model_config = ConfigDict(extra="allow")

    name: str
    enabled: bool = True
    cartridge_path: str | None = None  # defaults to ~/.teleclaude/company/domains/{name}/cartridges/
    guardian: DomainGuardianConfig = Field(default_factory=DomainGuardianConfig)
    autonomy: AutonomyMatrix = Field(default_factory=AutonomyMatrix)


class DomainsConfig(BaseModel):
    """Top-level configuration for all domain and personal event pipelines."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    base_path: str = "~/.teleclaude/company"
    personal_base_path: str = "~/.teleclaude/personal"
    helpdesk_path: str = "~/.teleclaude/helpdesk"
    domains: dict[str, DomainConfig] = Field(default_factory=dict)
