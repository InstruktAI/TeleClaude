"""The Config tab's daemon requests: what it reads and how it writes, as configuration operations.

The tab holds no write authority over a backing file. Every read is a `get`, `list`, `env-list`,
`person-secrets` or `validate` request and every write a `patch` or `env-set` request, run by the
daemon under the target clearance of the person operating the tab.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.config_handlers import EnvVarInfo, EnvVarStatus, ValidationResult
from teleclaude.config.operation_answers import (
    EnvironmentReferenceRow,
    EnvironmentVariablesAnswer,
    InstancesAnswer,
    PersonSecretsAnswer,
    RevisionAnswer,
    ValidationAnswer,
    ViewAnswer,
)
from teleclaude.config.subject_operations import (
    ENVIRONMENT_REFERENCES_KEY,
    ConfigFailureKind,
    ConfigOutcome,
    ConfigRequest,
    ConfigVerb,
)
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind

type Document = dict[str, object]  # guard: loose-dict - configuration view as the daemon answers it

_COMMAND_GET: Final = "config {kind} get"
_COMMAND_LIST: Final = "config {kind} list"
_COMMAND_PATCH: Final = "config {kind} patch"
_COMMAND_ENV_LIST: Final = "config env list"
_COMMAND_ENV_SET: Final = "config env set"
_COMMAND_VALIDATE: Final = "config validate"
# An environment request is cleared as the `telec config` command that changes the subject owning that environment.
_ENVIRONMENT_COMMAND: Final = {
    ConfigEnvironment.MACHINE: _COMMAND_ENV_SET,
    ConfigEnvironment.GLOBAL: _COMMAND_PATCH.format(kind=ConfigSubjectKind.GLOBAL.value),
    ConfigEnvironment.PERSON: _COMMAND_PATCH.format(kind=ConfigSubjectKind.PERSON.value),
}
_MASTER_SCOPED_KEY: Final = "master_scoped_not_applicable"
_JSON_MODE: Final = "json"
_SECTION_PATH_SEPARATOR: Final = "."
_NO_PAYLOAD: Final = "the daemon's configuration answer carries no payload"
_MALFORMED_ANSWER: Final = "the daemon's configuration answer does not match {answer}"
_REFERENCES: Final = TypeAdapter(list[EnvironmentReferenceRow])


class ConfigOperationFailed(Exception):
    """A configuration operation the daemon did not perform, with what the view presents."""

    def __init__(self, kind: ConfigFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class SubjectSnapshot:
    """One subject as `get` answered: its effective sections, its revision, and its environment references."""

    view: Document
    revision: str
    references: tuple[EnvironmentReferenceRow, ...] = field(default_factory=tuple)

    def section(self, name: str) -> Document:
        """One effective section of the subject, empty when the subject holds none."""
        section = self.view.get(name)
        return dict(section) if isinstance(section, Mapping) else {}

    def references_under(self, section: str) -> dict[str, EnvironmentReferenceRow]:
        """The section's references keyed by their path inside the section."""
        prefix = f"{section}{_SECTION_PATH_SEPARATOR}"
        return {
            reference.path.removeprefix(prefix): reference
            for reference in self.references
            if reference.path.startswith(prefix)
        }

    @property
    def outside_scope(self) -> tuple[str, ...]:
        """The master-scoped sections that do not apply to this computer."""
        value = self.view.get(_MASTER_SCOPED_KEY)
        return tuple(str(name) for name in value) if isinstance(value, list) else ()


@dataclass(frozen=True)
class PersonSecret:
    """One personal MCP secret's set state and the servers that require it; never its value."""

    name: str
    is_set: bool
    requiring_servers: tuple[str, ...]


@dataclass(frozen=True)
class PersonSecretInventory:
    """The registry-derived inventory of a person's personal secrets, or its storage being unavailable."""

    available: bool
    secrets: tuple[PersonSecret, ...] = field(default_factory=tuple)


def _payload(outcome: ConfigOutcome) -> Document:
    failure = outcome.failure
    if failure is not None:
        raise ConfigOperationFailed(failure.kind, failure.message)
    if outcome.payload is None:
        raise ConfigOperationFailed(ConfigFailureKind.INVALID, _NO_PAYLOAD)
    return outcome.payload


def _answer[AnswerT: BaseModel](answer: type[AnswerT], payload: Document) -> AnswerT:
    """The payload as the typed answer its operation declares."""
    try:
        return answer.model_validate(payload)
    except ValidationError as error:
        raise ConfigOperationFailed(
            ConfigFailureKind.INVALID, _MALFORMED_ANSWER.format(answer=answer.__name__)
        ) from error


def _snapshot(payload: Document) -> SubjectSnapshot:
    answer = _answer(ViewAnswer, payload)
    entries = answer.view.get(ENVIRONMENT_REFERENCES_KEY)
    references = tuple(_REFERENCES.validate_python(entries)) if isinstance(entries, list) else ()
    return SubjectSnapshot(view=answer.view, revision=answer.revision, references=references)


class ConfigOperations:
    """The Config tab's requests to the daemon's configuration operations."""

    def __init__(self, api: TelecAPIClient) -> None:
        self._api = api

    async def _run(self, request: ConfigRequest, command_path: str) -> Document:
        answer = await self._api.run_config_operation(request.model_dump(mode=_JSON_MODE), command_path)
        return _payload(ConfigOutcome.model_validate_json(answer))

    async def get(self, kind: ConfigSubjectKind, instance: str | None = None) -> SubjectSnapshot:
        """Read one subject's effective view, its revision, and its environment references."""
        request = ConfigRequest(verb=ConfigVerb.GET, kind=kind, instance=instance, request_id=str(uuid4()))
        return _snapshot(await self._run(request, _COMMAND_GET.format(kind=kind.value)))

    async def list_instances(self, kind: ConfigSubjectKind) -> list[str]:
        """The registered instances of a kind; a refusal is raised, never read as an empty roster."""
        request = ConfigRequest(verb=ConfigVerb.LIST, kind=kind, request_id=str(uuid4()))
        payload = await self._run(request, _COMMAND_LIST.format(kind=kind.value))
        return _answer(InstancesAnswer, payload).instances

    async def own_person_slug(self) -> str | None:
        """The slug of the registered person operating the tab, when they are one."""
        whoami = await self._api.whoami()
        return whoami.person_slug

    async def environment_variables(self) -> list[EnvVarStatus]:
        """The required environment variables and whether each is set; no value."""
        request = ConfigRequest(verb=ConfigVerb.ENV_LIST, request_id=str(uuid4()))
        answer = _answer(EnvironmentVariablesAnswer, await self._run(request, _COMMAND_ENV_LIST))
        return [
            EnvVarStatus(
                info=EnvVarInfo(name=row.name, adapter=row.service, description=row.description),
                is_set=row.is_set,
            )
            for row in answer.variables
        ]

    async def validate(self) -> list[ValidationResult]:
        """Run the full configuration validation."""
        request = ConfigRequest(verb=ConfigVerb.VALIDATE, request_id=str(uuid4()))
        answer = _answer(ValidationAnswer, await self._run(request, _COMMAND_VALIDATE))
        return [
            ValidationResult(
                area=row.area, passed=row.passed, errors=row.errors, suggestions=row.suggestions, notes=row.notes
            )
            for row in answer.results
        ]

    async def person_secrets(self, slug: str) -> PersonSecretInventory:
        """A person's personal secret inventory."""
        request = ConfigRequest(
            verb=ConfigVerb.PERSON_SECRETS, kind=ConfigSubjectKind.PERSON, instance=slug, request_id=str(uuid4())
        )
        answer = _answer(
            PersonSecretsAnswer, await self._run(request, _COMMAND_GET.format(kind=ConfigSubjectKind.PERSON.value))
        )
        return PersonSecretInventory(
            available=answer.available,
            secrets=tuple(
                PersonSecret(name=row.name, is_set=row.is_set, requiring_servers=tuple(row.requiring_servers))
                for row in answer.secrets
            ),
        )

    async def patch(self, kind: ConfigSubjectKind, instance: str | None, revision: str, patch: Document) -> str:
        """Apply a merge patch built from the revision last read; answers the subject's new revision."""
        request = ConfigRequest(
            verb=ConfigVerb.PATCH,
            kind=kind,
            instance=instance,
            patch=patch,
            revision=revision,
            request_id=str(uuid4()),
        )
        payload = await self._run(request, _COMMAND_PATCH.format(kind=kind.value))
        return _answer(RevisionAnswer, payload).revision

    async def set_environment(
        self,
        environment: ConfigEnvironment,
        *,
        instance: str | None = None,
        values: Sequence[tuple[str, str]] = (),
        clear: Sequence[str] = (),
    ) -> None:
        """Set or clear variables in one environment; a pair with an empty value leaves its variable as it is."""
        request = ConfigRequest(
            verb=ConfigVerb.ENV_SET,
            environment=environment,
            instance=instance,
            env_pairs=[[name, value] for name, value in values],
            env_clear=list(clear),
            request_id=str(uuid4()),
        )
        await self._run(request, _ENVIRONMENT_COMMAND[environment])
