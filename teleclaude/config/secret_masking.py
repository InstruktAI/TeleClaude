"""Mask the platform's secrets in text before it leaves the process that produced it.

A secret is a value the configuration declares sensitive: a field annotated ``SENSITIVE`` in the
machine, global, project, person or company configuration, or a company service credential.
Every other value stays readable. A value a command obtains from anywhere else is not declared
a secret and is not masked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from teleclaude.closed_model import field_is_sensitive
from teleclaude.config._environment import CompanyCredentialsError
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.loader import (
    list_company_configs,
    load_company_credentials,
    load_declared_project_config,
    load_global_config,
    load_person_config_for_entry,
)
from teleclaude.config.machine import loaded_machine_config

_MASK: Final = "***"
_SECRETS_UNKNOWN: Final = "The declared secrets cannot be read: {error}"


def declared_secret_values(project_root: Path) -> frozenset[str]:
    """Every secret the configuration a command in ``project_root`` runs under declares.

    Raises ``ConfigLoadError`` whenever the secrets cannot be known: a configuration that does
    not load, a missing or unreadable file, or company credentials that cannot be read safely.
    """
    try:
        return _declared_secret_values(project_root)
    except (CompanyCredentialsError, OSError) as error:
        raise ConfigLoadError(_SECRETS_UNKNOWN.format(error=error)) from error


def _declared_secret_values(project_root: Path) -> frozenset[str]:
    global_config = load_global_config()
    models: list[BaseModel] = [loaded_machine_config(), global_config]
    project = load_declared_project_config(project_root)
    if project is not None:
        models.append(project)
    for person in global_config.people:
        person_config = load_person_config_for_entry(person)
        if person_config is not None:
            models.append(person_config)
    values: set[str] = set()
    for slug, company in list_company_configs():
        models.append(company)
        values.update(load_company_credentials(slug).values())
    for model in models:
        values.update(sensitive_values(model))
    return frozenset(value for value in values if value)


def sensitive_values(model: BaseModel) -> set[str]:
    """The values of every field annotated ``SENSITIVE`` in a loaded model, at any depth."""
    values: set[str] = set()
    for name, field_info in type(model).model_fields.items():
        value = getattr(model, name)
        if field_is_sensitive(field_info):
            values.update(_leaf_texts(value))
        else:
            values.update(_nested_sensitive_values(value))
    return values


def mask_secret_values(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of every secret with a mask, longest first."""
    for secret in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(secret, _MASK)
    return text


def _nested_sensitive_values(value: object) -> set[str]:
    if isinstance(value, BaseModel):
        return sensitive_values(value)
    if isinstance(value, Mapping):
        return {found for item in value.values() for found in _nested_sensitive_values(item)}
    if isinstance(value, (list, tuple)):
        return {found for item in value for found in _nested_sensitive_values(item)}
    return set()


def _leaf_texts(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, Mapping):
        return {text for item in value.values() for text in _leaf_texts(item)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {text for item in value for text in _leaf_texts(item)}
    return {str(value)}
