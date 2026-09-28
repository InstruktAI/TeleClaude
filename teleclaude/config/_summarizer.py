"""Summarizer provider configuration: local (OpenAI-compatible) + cloud fallbacks."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from teleclaude.closed_model import SENSITIVE, ClosedModel
from teleclaude.config._coerce import TRUTHY, TRUTHY_TEXT

_PROVIDER_PRIORITY_PATH = "config.yml:summarizer.provider_priority"
_UNKNOWN_PROVIDER_ERROR = "Invalid config key `{path}`: unknown provider(s) {unknown}. Allowed values: {allowed}."
_LOCAL_KEY = "local"
_ENABLED_KEY = "enabled"
_BASE_URL_KEY = "base_url"
_MODEL_KEY = "model"
_API_KEY_KEY = "api_key"
_PROVIDER_PRIORITY_KEY = "provider_priority"


class SummarizerProvider(StrEnum):
    """Cloud summarizer providers with schema-declared configuration blocks."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class SummarizerLocalConfig(ClosedModel):
    """Local (OpenAI-compatible) summarizer provider, e.g. LM Studio."""

    enabled: TRUTHY = False
    base_url: Annotated[TRUTHY_TEXT, SENSITIVE] = "http://localhost:1234/v1"
    model: Annotated[TRUTHY_TEXT, SENSITIVE] = None
    api_key: Annotated[TRUTHY_TEXT, SENSITIVE] = None


class SummarizerCloudConfig(ClosedModel):
    """Typed model and credential for one cloud summarizer provider."""

    model: Annotated[TRUTHY_TEXT, SENSITIVE] = None
    api_key: Annotated[TRUTHY_TEXT, SENSITIVE] = None


class SummarizerConfig(ClosedModel):
    """Summary/title generation providers, tried in order.

    ``local`` is tried first when enabled; then the cloud providers in
    ``provider_priority`` are tried in order, each skipped when its API key
    is absent. Each cloud provider owns its model and credential together.
    """

    local: SummarizerLocalConfig = Field(default_factory=SummarizerLocalConfig)
    provider_priority: list[SummarizerProvider] = Field(default_factory=list)
    openai: SummarizerCloudConfig = Field(default_factory=SummarizerCloudConfig)
    anthropic: SummarizerCloudConfig = Field(default_factory=SummarizerCloudConfig)
    google: SummarizerCloudConfig = Field(default_factory=SummarizerCloudConfig)

    @model_validator(mode="before")
    @classmethod
    def _normalize_provider_sections(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        local = data.get(_LOCAL_KEY)
        if local is None:
            data[_LOCAL_KEY] = {
                _ENABLED_KEY: False,
                _BASE_URL_KEY: None,
                _MODEL_KEY: None,
                _API_KEY_KEY: None,
            }
        elif isinstance(local, Mapping):
            local_data = dict(local)
            local_data.setdefault(_ENABLED_KEY, False)
            local_data.setdefault(_BASE_URL_KEY, None)
            local_data.setdefault(_MODEL_KEY, None)
            local_data.setdefault(_API_KEY_KEY, None)
            data[_LOCAL_KEY] = local_data
        data.setdefault(_PROVIDER_PRIORITY_KEY, [])
        if data.get(_PROVIDER_PRIORITY_KEY) is None:
            data[_PROVIDER_PRIORITY_KEY] = []
        for provider in SummarizerProvider:
            if data.get(provider.value) is None:
                data[provider.value] = {}
        return data

    @field_validator(_PROVIDER_PRIORITY_KEY, mode="before")
    @classmethod
    def _parse_provider_priority(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        providers: list[SummarizerProvider] = []
        unknown: list[str] = []
        for item in value:
            if not item:
                continue
            if isinstance(item, (Mapping, list)):
                return value
            provider = str(item)
            try:
                providers.append(SummarizerProvider(provider))
            except ValueError:
                unknown.append(provider)
        if unknown:
            allowed = ", ".join(provider.value for provider in SummarizerProvider)
            raise ValueError(
                _UNKNOWN_PROVIDER_ERROR.format(
                    path=_PROVIDER_PRIORITY_PATH,
                    unknown=", ".join(unknown),
                    allowed=allowed,
                )
            )
        return providers
