"""Summarizer provider configuration: local (OpenAI-compatible) + cloud fallbacks."""

from __future__ import annotations

from dataclasses import dataclass, field

KNOWN_CLOUD_PROVIDERS = ("openai", "anthropic", "google")


@dataclass
class SummarizerLocalConfig:
    """Local (OpenAI-compatible) summarizer provider, e.g. LM Studio."""

    enabled: bool = False
    base_url: str | None = "http://localhost:1234/v1"  # OpenAI-compatible endpoint
    model: str | None = None
    api_key: str | None = None


@dataclass
class SummarizerCloudConfig:
    """Typed model and credential for one cloud summarizer provider."""

    model: str | None = None
    api_key: str | None = None


@dataclass
class SummarizerConfig:
    """Summary/title generation providers, tried in order.

    ``local`` is tried first when enabled; then the cloud providers in
    ``provider_priority`` are tried in order, each skipped when its API key
    is absent. Each cloud provider owns its model and credential together.
    """

    local: SummarizerLocalConfig = field(default_factory=SummarizerLocalConfig)
    provider_priority: list[str] = field(default_factory=list)
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
    priority = [str(p) for p in priority_obj if p] if isinstance(priority_obj, list) else []
    unknown = [p for p in priority if p not in KNOWN_CLOUD_PROVIDERS]
    if unknown:
        raise ValueError(
            f"Invalid config key `config.yml:summarizer.provider_priority`: unknown provider(s) "
            f"{', '.join(unknown)}. Allowed values: {', '.join(KNOWN_CLOUD_PROVIDERS)}."
        )
    providers: dict[str, SummarizerCloudConfig] = {}
    for provider in KNOWN_CLOUD_PROVIDERS:
        provider_obj = raw.get(provider)
        provider_raw = provider_obj if isinstance(provider_obj, dict) else {}
        providers[provider] = SummarizerCloudConfig(
            model=str(provider_raw["model"]) if provider_raw.get("model") else None,
            api_key=str(provider_raw["api_key"]) if provider_raw.get("api_key") else None,
        )
    return SummarizerConfig(
        local=local,
        provider_priority=priority,
        openai=providers["openai"],
        anthropic=providers["anthropic"],
        google=providers["google"],
    )
