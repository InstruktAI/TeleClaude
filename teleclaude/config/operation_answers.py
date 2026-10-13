"""The typed answers of configuration operations: what each operation's payload carries, named once.

The producer builds an answer from one of these and the consumer reads it back through the same one, so
neither side holds the payload's keys. Each is closed to what it declares and tolerant of fields a later
build adds.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from teleclaude.config_subjects import ConfigEnvironment

CONFIG_API_PREFIX: Final = "/config"
CONFIG_OPERATIONS_ROUTE: Final = "/operations"
CONFIG_OPERATIONS_PATH: Final = f"{CONFIG_API_PREFIX}{CONFIG_OPERATIONS_ROUTE}"


class OperationAnswer(BaseModel):
    """Base of the answers: immutable, ignoring fields a newer daemon adds."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class ViewAnswer(OperationAnswer):
    """`get`: the subject's effective view and the revision a later write is built from."""

    view: dict[str, object]  # guard: loose-dict - effective sections and projections, per subject kind
    revision: str


class RevisionAnswer(OperationAnswer):
    """`patch`: the subject's revision after the write."""

    revision: str


class InstancesAnswer(OperationAnswer):
    """`list`: the registered instances of a kind."""

    instances: list[str]


class EnvironmentReferenceRow(OperationAnswer):
    """A field whose stored value is an environment reference: where it is, what it names, whether it resolves."""

    path: str
    variable: str
    environment: ConfigEnvironment
    has_value: bool


class EnvironmentVariableRow(OperationAnswer):
    """One required environment variable and whether it is set; never its value."""

    name: str
    service: str
    is_set: bool
    description: str


class EnvironmentVariablesAnswer(OperationAnswer):
    """`env-list`: the required environment variables."""

    variables: list[EnvironmentVariableRow]


class ValidationRow(OperationAnswer):
    """One validated area of the configuration."""

    area: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ValidationAnswer(OperationAnswer):
    """`validate`: the validated areas."""

    results: list[ValidationRow]


class EnvironmentChangeAnswer(OperationAnswer):
    """`env-set`: the variables set and the variables cleared."""

    updated: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)


class PersonSecretRow(OperationAnswer):
    """One personal MCP secret's set state and the servers that require it; never its value."""

    name: str
    is_set: bool
    requiring_servers: list[str] = Field(default_factory=list)


class PersonSecretsAnswer(OperationAnswer):
    """`person-secrets`: a person's secret inventory, or that their secret storage is unavailable."""

    available: bool
    secrets: list[PersonSecretRow] = Field(default_factory=list)
