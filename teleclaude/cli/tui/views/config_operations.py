"""The Config tab's typed editor, environment, list and validation requests to the daemon."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config.operation_answers import (
    EditorViewAnswer,
    EnvironmentVariablesAnswer,
    InstancesAnswer,
    RevisionAnswer,
    ValidationAnswer,
)
from teleclaude.config.operation_requests import (
    ConfigEditIntent,
    ConfigFailureKind,
    ConfigOutcome,
    ConfigRequest,
    ConfigVerb,
)
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind

type Document = dict[str, object]  # guard: loose-dict - configuration view as the daemon answers it


@dataclass(frozen=True)
class EnvVarInfo:
    """Display metadata for one required environment variable."""

    name: str
    adapter: str
    description: str


@dataclass(frozen=True)
class EnvVarStatus:
    """One environment row projected from the daemon's presence-only answer."""

    info: EnvVarInfo
    is_set: bool


@dataclass(frozen=True)
class ValidationResult:
    """One validation area as the TUI presents it."""

    area: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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
_JSON_MODE: Final = "json"
_NO_PAYLOAD: Final = "the daemon's configuration answer carries no payload"
_MALFORMED_ANSWER: Final = "the daemon's configuration answer does not match {answer}"


class ConfigOperationFailed(Exception):
    """A configuration operation the daemon did not perform, with what the view presents."""

    def __init__(self, kind: ConfigFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


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


class ConfigOperations:
    """The Config tab's requests to the daemon's configuration operations."""

    def __init__(self, api: TelecAPIClient) -> None:
        self._api = api

    async def _run(self, request: ConfigRequest, command_path: str) -> Document:
        answer = await self._api.run_config_operation(request.model_dump(mode=_JSON_MODE), command_path)
        return _payload(ConfigOutcome.model_validate_json(answer))

    async def editor(self, kind: ConfigSubjectKind, instance: str | None = None) -> EditorViewAnswer:
        """Read the configuration owner's display-ready editor projection."""
        request = ConfigRequest(verb=ConfigVerb.EDITOR_GET, kind=kind, instance=instance, request_id=str(uuid4()))
        return _answer(EditorViewAnswer, await self._run(request, _COMMAND_GET.format(kind=kind.value)))

    async def edit_field(
        self,
        kind: ConfigSubjectKind,
        instance: str | None,
        revision: str,
        editor_revision: str,
        field_id: str,
        intent: ConfigEditIntent,
        value: object = None,
    ) -> EditorViewAnswer:
        """Submit one field identity and its explicit write intent to the configuration owner."""
        request = ConfigRequest(
            verb=ConfigVerb.FIELD_EDIT,
            kind=kind,
            instance=instance,
            revision=revision,
            editor_revision=editor_revision,
            field_id=field_id,
            edit_intent=intent,
            value=value,
            request_id=str(uuid4()),
        )
        return _answer(EditorViewAnswer, await self._run(request, _COMMAND_PATCH.format(kind=kind.value)))

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
