"""Semantic person-tier Discord voice credential configuration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from teleclaude.config._environment import expand_environment_references, read_environment_file
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.migrations import Destination, carry_pending, upcast
from teleclaude.config.person_secrets import (
    clear_person_mcp_secret,
    person_secret_store_path,
    replace_person_mcp_secret,
    secure_person_secret_store,
)
from teleclaude.config.schema import ConfigKind, PersonConfig
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.models import JsonDict
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import PEOPLE_DIR, ConfigFileName
from teleclaude.slug import validate_slug

_CANONICAL_DISCORD_TOKEN_ENV = "DISCORD_TOKEN"
_LEGACY_DISCORD_TOKEN_ENV = "DISCORD_BOT_TOKEN"
_TOKEN_REFERENCE = f"${{{_CANONICAL_DISCORD_TOKEN_ENV}}}"


def _ignore_migration_delivery(_destination: Destination) -> None:
    """Keep migration deliveries outside this credential writer's result."""


@dataclass(frozen=True)
class PersonVoiceBotConfiguration:
    """Secret-safe result of binding one person's Discord voice bot."""

    person_slug: str
    environment_name: str
    environment_secured: bool


def configure_person_discord_voice_bot(
    person_slug: str,
    resolved_machine_token: str,
    *,
    people_dir: Path = PEOPLE_DIR,
) -> PersonVoiceBotConfiguration:
    """Copy the active Discord token into a person's tier and bind its reference."""
    validate_slug(person_slug)
    if not resolved_machine_token.strip():
        raise ValueError("The machine Discord token is unavailable")

    person_dir = people_dir / person_slug
    overlay_path = person_dir / ConfigFileName.OVERLAY
    if not overlay_path.is_file():
        raise FileNotFoundError(f"Person config does not exist: {overlay_path}")

    with file_transaction(overlay_path) as transaction:
        stored = _load_mapping(transaction.read_text(), overlay_path)
        subject = SubjectRef(ConfigSubjectKind.PERSON, person_slug)
        document = cast(JsonDict, upcast(stored, subject))
        candidate = _bind_voice_token(document)
        environment = read_environment_file(
            person_secret_store_path(person_slug, people_dir=people_dir),
            owner_only=True,
        )
        environment[_CANONICAL_DISCORD_TOKEN_ENV] = resolved_machine_token
        expanded = expand_environment_references(candidate, environment, config_path=overlay_path)
        PersonConfig.model_validate(expanded)
        carry_pending(stored, subject, delivered=_ignore_migration_delivery)
        environment_secured = secure_person_secret_store(person_slug, people_dir=people_dir)
        replace_person_mcp_secret(
            person_slug,
            _CANONICAL_DISCORD_TOKEN_ENV,
            resolved_machine_token,
            people_dir=people_dir,
        )
        transaction.replace_text(
            render_declared_config(
                ConfigKind.PERSON,
                candidate,
            )
        )

    clear_person_mcp_secret(person_slug, _LEGACY_DISCORD_TOKEN_ENV, people_dir=people_dir)

    return PersonVoiceBotConfiguration(
        person_slug=person_slug,
        environment_name=_CANONICAL_DISCORD_TOKEN_ENV,
        environment_secured=environment_secured,
    )


def _load_mapping(content: str, path: Path) -> JsonDict:
    parsed = round_trip_yaml().load(content) if content else {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Person configuration must be a mapping: {path}")
    return cast(JsonDict, parsed)


def _bind_voice_token(document: JsonDict) -> JsonDict:
    candidate = deepcopy(document)
    creds = candidate.setdefault("creds", {})
    if not isinstance(creds, dict):
        raise ValueError("Person configuration creds must be a mapping")
    discord = creds.setdefault("discord", {})
    if not isinstance(discord, dict):
        raise ValueError("Person Discord credentials must be a mapping")
    discord["voice_bot_token"] = _TOKEN_REFERENCE
    discord.pop("voice_channel_id", None)
    return candidate
