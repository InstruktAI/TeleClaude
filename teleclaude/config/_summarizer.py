"""Summarizer provider configuration: local (OpenAI-compatible) + cloud fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from teleclaude.config._strictness import SCALAR, ClosedMapping, InputList
from teleclaude.config.tiers import SENSITIVE_METADATA_KEY


class SummarizerProvider(StrEnum):
    """Cloud summarizer providers with schema-declared configuration blocks."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


_CLOUD_PROVIDER_INPUT = ClosedMapping({"model": SCALAR, "api_key": SCALAR})
SUMMARIZER_INPUT = ClosedMapping(
    {
        "local": ClosedMapping({"enabled": SCALAR, "base_url": SCALAR, "model": SCALAR, "api_key": SCALAR}),
        "provider_priority": InputList(SCALAR),
        "openai": _CLOUD_PROVIDER_INPUT,
        "anthropic": _CLOUD_PROVIDER_INPUT,
        "google": _CLOUD_PROVIDER_INPUT,
    }
)


@dataclass
class SummarizerLocalConfig:
    """Local (OpenAI-compatible) summarizer provider, e.g. LM Studio."""

    enabled: bool = False
    base_url: str | None = field(default="http://localhost:1234/v1", metadata={SENSITIVE_METADATA_KEY: True})
    model: str | None = field(default=None, metadata={SENSITIVE_METADATA_KEY: True})
    api_key: str | None = field(default=None, metadata={SENSITIVE_METADATA_KEY: True})


@dataclass
class SummarizerCloudConfig:
    """Typed model and credential for one cloud summarizer provider."""

    model: str | None = field(default=None, metadata={SENSITIVE_METADATA_KEY: True})
    api_key: str | None = field(default=None, metadata={SENSITIVE_METADATA_KEY: True})


@dataclass
class SummarizerConfig:
    """Summary/title generation providers, tried in order.

    ``local`` is tried first when enabled; then the cloud providers in
    ``provider_priority`` are tried in order, each skipped when its API key
    is absent. Each cloud provider owns its model and credential together.
    """

    local: SummarizerLocalConfig = field(default_factory=SummarizerLocalConfig)
    provider_priority: list[SummarizerProvider] = field(default_factory=list)
    openai: SummarizerCloudConfig = field(default_factory=SummarizerCloudConfig)
    anthropic: SummarizerCloudConfig = field(default_factory=SummarizerCloudConfig)
    google: SummarizerCloudConfig = field(default_factory=SummarizerCloudConfig)


def parse_summarizer_config(
    raw: dict[str, object] | None,  # guard: loose-dict - YAML config value
) -> SummarizerConfig | None:
    """Parse the summarizer provider config from a raw YAML mapping."""
    if not raw:
        return None
    local_obj = raw.get("local")
    local_raw = local_obj if isinstance(local_obj, dict) else {}
    local = SummarizerLocalConfig(
        enabled=bool(local_raw.get("enabled", False)),
        base_url=str(local_raw["base_url"]) if local_raw.get("base_url") else None,
        model=str(local_raw["model"]) if local_raw.get("model") else None,
        api_key=str(local_raw["api_key"]) if local_raw.get("api_key") else None,
    )
    priority_obj = raw.get("provider_priority", [])
    priority: list[SummarizerProvider] = []
    unknown: list[str] = []
    if isinstance(priority_obj, list):
        for provider in priority_obj:
            if not provider:
                continue
            try:
                priority.append(SummarizerProvider(str(provider)))
            except ValueError:
                unknown.append(str(provider))
    if unknown:
        raise ValueError(
            f"Invalid config key `config.yml:summarizer.provider_priority`: unknown provider(s) "
            f"{', '.join(unknown)}. Allowed values: {', '.join(provider.value for provider in SummarizerProvider)}."
        )
    providers: dict[SummarizerProvider, SummarizerCloudConfig] = {}
    for provider in SummarizerProvider:
        provider_obj = raw.get(provider.value)
        provider_raw = provider_obj if isinstance(provider_obj, dict) else {}
        providers[provider] = SummarizerCloudConfig(
            model=str(provider_raw["model"]) if provider_raw.get("model") else None,
            api_key=str(provider_raw["api_key"]) if provider_raw.get("api_key") else None,
        )
    return SummarizerConfig(
        local=local,
        provider_priority=priority,
        openai=providers[SummarizerProvider.OPENAI],
        anthropic=providers[SummarizerProvider.ANTHROPIC],
        google=providers[SummarizerProvider.GOOGLE],
    )
