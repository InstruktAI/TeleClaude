"""Portable request and outcome contracts for configuration operations.

This module deliberately contains no operation handlers or runtime services so
clients can construct and decode configuration requests without loading their
execution path.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind

type Payload = dict[str, object]  # guard: loose-dict - heterogeneous per-operation config payload


class ConfigVerb(StrEnum):
    """The closed vocabulary of configuration operations a request can ask for."""

    LIST = "list"
    GET = "get"
    INIT = "init"
    PATCH = "patch"
    REMOVE = "remove"
    CREATE = "create"
    INVITE = "invite"
    DISCORD_VOICE_BOT = "discord-voice-bot"
    HELP_DESK_LINKS = "help-desk-links"
    VALIDATE = "validate"
    ENV_LIST = "env-list"
    ENV_SET = "env-set"
    PERSON_SECRETS = "person-secrets"
    JOB_SUBSCRIPTION = "job-subscription"
    EDITOR_GET = "editor-get"
    FIELD_EDIT = "field-edit"
    PROJECT_ADOPT = "project-adopt"
    INVITATION_DESTINATION = "invitation-destination"


class ConfigEditIntent(StrEnum):
    """The explicit action a configuration field edit carries."""

    KEEP = "keep"
    REPLACE = "replace"
    CLEAR = "clear"


class ConfigFailureKind(StrEnum):
    """Why a configuration operation did not happen."""

    REFUSED = "refused"
    STALE_REVISION = "stale_revision"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    PARTIAL_COMMIT = "partial_commit"


class ConfigRequest(BaseModel):
    """One configuration operation asked of the computer that owns the configuration."""

    model_config = ConfigDict(frozen=True)

    verb: ConfigVerb
    kind: ConfigSubjectKind | None = None
    instance: str | None = None
    request_id: str
    fields: Payload | None = None
    patch: Payload | None = None
    revision: str | None = None
    editor_revision: str | None = None
    delete_dir: bool = False
    name: str | None = None
    company: str | None = None
    path: str | None = None
    env_pairs: list[list[str]] = Field(default_factory=list)
    # The environment an `env-set` request changes; the machine's when absent. A person's names that person in `instance`.
    environment: ConfigEnvironment | None = None
    # Variables an `env-set` request clears; a pair with an empty value leaves its variable as it is.
    env_clear: list[str] = Field(default_factory=list)
    job: str | None = None
    enabled: bool = True
    # The project the command acts on, which the computer answering judges the caller's role at.
    project: str | None = None
    field_id: str | None = None
    edit_intent: ConfigEditIntent | None = None
    value: object | None = None
    # Invocation directory retained as request input so the daemon resolves project adoption.
    invocation_cwd: str | None = None


class ConfigFailure(BaseModel):
    """A configuration operation that did not happen, with what its presentation needs."""

    model_config = ConfigDict(frozen=True)

    kind: ConfigFailureKind
    message: str
    required_standing: str | None = None
    expected: str | None = None
    actual: str | None = None


class ConfigOutcome(BaseModel):
    """The structured answer of one configuration operation."""

    model_config = ConfigDict(frozen=True)

    payload: Payload | None = None
    failure: ConfigFailure | None = None


# Lightweight response keys shared by operation producers and adapters.
INVITE_UNAVAILABLE_PROVIDERS_KEY = "unavailable_providers"
INVITE_EMAIL_ENABLED_KEY = "email_enabled"
VALIDATE_NOTES_KEY = "notes"
ENVIRONMENT_REFERENCES_KEY = "environment_references"
