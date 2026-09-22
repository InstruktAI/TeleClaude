"""Domain event processing configuration schema."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from teleclaude.closed_model import ClosedModel


class AutonomyLevel(str, Enum):
    """Execution autonomy levels for domain cartridges."""

    MANUAL = "manual"
    NOTIFY = "notify"
    AUTO_NOTIFY = "auto_notify"
    AUTONOMOUS = "autonomous"


class AutonomyMatrix(ClosedModel):
    """Priority-ordered autonomy overrides for domains, cartridges, and events."""

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


class DomainGuardianConfig(ClosedModel):
    """Guardian agent settings used when a domain requires evaluation."""

    agent: str = "claude"
    mode: str = "med"
    enabled: bool = True
    evaluation_prompt: str | None = None


class DomainConfig(ClosedModel):
    """Configuration for a single domain-specific event pipeline."""

    name: str
    enabled: bool = True
    guardian: DomainGuardianConfig = Field(default_factory=DomainGuardianConfig)
    autonomy: AutonomyMatrix = Field(default_factory=AutonomyMatrix)


class DomainsConfig(ClosedModel):
    """Top-level configuration for repo-owned domain event pipelines."""

    enabled: bool = True
    domains: dict[str, DomainConfig] = Field(default_factory=dict)
