"""Configuration subject operations: what each `telec config` operation does, as data in and data out.

Every operation takes the resolved caller's standing and a request, decides target
clearance (`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`),
runs the matching config resource verb, and answers with a structured outcome. The
CLI runs these in its own process when it addresses this computer; the daemon runs the
same functions for a command addressed here from another computer. Neither presents
anything: rendering, masking included, is what the outcome's payload already carries.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from teleclaude.cli.config_handlers import check_env_vars, validate_all
from teleclaude.config._environment import (
    CompanyCredentialsError,
    InvalidEnvironmentReferenceError,
    write_environment_value,
)
from teleclaude.config.effective_view import InvalidEffectiveValue, effective_sections, without_masked_values
from teleclaude.config.jobs import plan_job_subscription
from teleclaude.config.loader import load_global_config
from teleclaude.config.machine import config
from teleclaude.config.person_voice import configure_person_discord_voice_bot
from teleclaude.config.project_subject_init import create_project_subject
from teleclaude.config.resource_contract import (
    InvalidCandidate,
    PartialCommitFailure,
    ReadOnlyProjection,
    SubjectNotFound,
    SubjectView,
)
from teleclaude.config.resources import (
    affected_sections,
    init_subject,
    list_subjects,
    patch_subject,
    read_subject,
    remove_person_subject,
)
from teleclaude.config.revision import StaleRevision
from teleclaude.config.roster import RosterRefused
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.configuration_clearance import (
    ConfigurationOperation,
    ConfigurationStanding,
    ConfigurationTarget,
    ProjectCreationForm,
    decide,
)
from teleclaude.core.endpoints import (
    TELEGRAM_START_PARAMETER_MAX,
    DeskIdentifier,
    desk_home_present,
    local_desk_endpoint,
)
from teleclaude.core.inbound.fleet import observe_fleet_from_heartbeats
from teleclaude.core.models import HelpDeskKind
from teleclaude.core.organization import person_roles
from teleclaude.invite import invite_person, render_help_desk_links
from teleclaude.paths import PROJECT_ENV_PATH
from teleclaude.project_setup.init_flow import (
    CompanyHomeDestination,
    PersonHomeDestination,
    PlatformPathDestination,
    ProjectDestination,
)

type Payload = dict[str, object]  # guard: loose-dict - heterogeneous per-operation config payload

_DESK_KIND_BY_SUBJECT: Final = {
    ConfigSubjectKind.COMPANY: HelpDeskKind.COMPANY,
    ConfigSubjectKind.PROJECT: HelpDeskKind.PROJECT,
}
_ROLES_FIELD = "roles"
_FORBIDDEN_FOR_CUSTOMER = "Permission denied. This operation requires member role or higher."
_NO_PERSON_HOME = "creating in your own home needs a registered person."
_RELATIVE_DESTINATION = "a project destination path must be absolute: {path}"
_DESK_NOT_ENABLED = "help desk of {kind} {slug} is not enabled"
_DESK_NOT_HOSTED = "this computer does not host the help desk of {kind} {slug}"
_DESK_NOT_ON_MASTER = "help desks run on the mesh master, and this computer is not the master"
_FLEET_UNOBSERVABLE = "cannot observe the fleet: {error}"
_FLEET_LAGGING = "help-desk entry is not served until every computer runs it; lagging: {computers}"
_LIST_SEPARATOR = ", "
_NO_TOKEN = ""
_PROJECT_SECTION = "project"
_JOBS_SECTION = "jobs"
_INVALID_PROJECT_SECTION = "Project subject has no writable project section"
_INVALID_JOBS_ARRAY = "Project subject has an invalid jobs array"


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
    JOB_SUBSCRIPTION = "job-subscription"


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
    delete_dir: bool = False
    name: str | None = None
    company: str | None = None
    path: str | None = None
    env_pairs: list[list[str]] = Field(default_factory=list)
    job: str | None = None
    enabled: bool = True
    # The project the command acts on, which the computer answering judges the caller's role at.
    project: str | None = None


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


def _done(payload: Payload) -> ConfigOutcome:
    return ConfigOutcome(payload=_wire_safe(payload))


def _failed(kind: ConfigFailureKind, error: Exception) -> ConfigOutcome:
    return ConfigOutcome(failure=ConfigFailure(kind=kind, message=str(error)))


def _invalid(message: str) -> ConfigOutcome:
    return ConfigOutcome(failure=ConfigFailure(kind=ConfigFailureKind.INVALID, message=message))


def _wire_safe(payload: Payload) -> Payload:
    """The payload as plain JSON values, the way the CLI renders any view."""
    plain: Payload = json.loads(json.dumps(payload, default=_json_default))
    return plain


def _json_default(value: object) -> object:
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _refusal(
    standing: ConfigurationStanding,
    request: ConfigRequest,
    operation: ConfigurationOperation,
    *,
    instance: str | None,
    sections: frozenset[str] = frozenset(),
    creation_form: ProjectCreationForm | None = None,
) -> ConfigOutcome | None:
    """Target clearance for the operation; a refusal is the operation's whole outcome."""
    assert request.kind is not None
    target = ConfigurationTarget(
        kind=request.kind,
        instance=instance,
        operation=operation,
        sections=sections,
        creation_form=creation_form,
    )
    decision = decide(standing, target, request_id=request.request_id)
    if decision.allowed:
        return None
    return ConfigOutcome(
        failure=ConfigFailure(
            kind=ConfigFailureKind.REFUSED,
            message=decision.reason,
            required_standing=decision.required_standing.value,
        )
    )


def _subject_ref(request: ConfigRequest) -> SubjectRef:
    assert request.kind is not None
    return SubjectRef(request.kind, request.instance)


def _view_payload(view: SubjectView) -> Payload:
    return {"sections": dict(view.sections), "revision": view.revision}


async def _list(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    assert request.kind is not None
    refused = _refusal(standing, request, ConfigurationOperation.LIST, instance=None)
    if refused is not None:
        return refused
    refs = await asyncio.to_thread(list_subjects, request.kind)
    return _done({"instances": [ref.instance for ref in refs]})


async def _get(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.GET, instance=request.instance)
    if refused is not None:
        return refused
    try:
        view = await asyncio.to_thread(read_subject, _subject_ref(request))
        read_only = dict(view.read_only)
        if request.kind is ConfigSubjectKind.PERSON and request.instance is not None:
            read_only[_ROLES_FIELD] = person_roles(request.instance)
        sections = effective_sections(view)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidEffectiveValue, InvalidEnvironmentReferenceError, CompanyCredentialsError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done({"view": {**sections, **read_only}, "revision": view.revision})


async def _init(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    assert request.kind is not None
    refused = _refusal(standing, request, ConfigurationOperation.INIT, instance=None)
    if refused is not None:
        return refused
    try:
        view = await asyncio.to_thread(
            init_subject, SubjectRef(request.kind, None), request.fields, request_id=request.request_id
        )
    except PartialCommitFailure as error:
        return _failed(ConfigFailureKind.PARTIAL_COMMIT, error)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidCandidate, ValueError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done(_view_payload(view))


async def _patch(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    assert request.kind is not None and request.patch is not None and request.revision is not None
    ref = _subject_ref(request)
    patch = without_masked_values(request.kind, request.patch)
    refused = _refusal(
        standing,
        request,
        ConfigurationOperation.PATCH,
        instance=request.instance,
        sections=affected_sections(ref, patch),
    )
    if refused is not None:
        return refused
    try:
        view = await asyncio.to_thread(
            patch_subject, ref, patch, expected_revision=request.revision, request_id=request.request_id
        )
    except StaleRevision as error:
        return ConfigOutcome(
            failure=ConfigFailure(
                kind=ConfigFailureKind.STALE_REVISION,
                message=str(error),
                expected=str(error.expected),
                actual=str(error.actual),
            )
        )
    except PartialCommitFailure as error:
        return _failed(ConfigFailureKind.PARTIAL_COMMIT, error)
    except (InvalidCandidate, ReadOnlyProjection, RosterRefused) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    return _done(_view_payload(view))


async def _remove(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.REMOVE, instance=request.instance)
    if refused is not None:
        return refused
    try:
        outcome = await asyncio.to_thread(
            remove_person_subject,
            _subject_ref(request),
            delete_dir=request.delete_dir,
            request_id=request.request_id,
        )
    except PartialCommitFailure as error:
        return _failed(ConfigFailureKind.PARTIAL_COMMIT, error)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    return _done(
        {
            "companies_written": list(outcome.companies_written),
            "removed_assignments": [list(pair) for pair in outcome.removed_assignments],
        }
    )


def _creation_form(request: ConfigRequest) -> ProjectCreationForm:
    if request.path is not None:
        return ProjectCreationForm.PLATFORM_PATH
    if request.company is not None:
        return ProjectCreationForm.COMPANY
    return ProjectCreationForm.OWN_HOME


async def _create(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    assert request.name is not None
    form = _creation_form(request)
    refused = _refusal(
        standing,
        request,
        ConfigurationOperation.CREATE,
        instance=request.company if form is ProjectCreationForm.COMPANY else None,
        creation_form=form,
    )
    if refused is not None:
        return refused
    destination: ProjectDestination
    if form is ProjectCreationForm.PLATFORM_PATH and request.path is not None:
        path = Path(request.path).expanduser()
        if not path.is_absolute():
            return _invalid(_RELATIVE_DESTINATION.format(path=request.path))
        destination = PlatformPathDestination(path)
    elif form is ProjectCreationForm.COMPANY and request.company is not None:
        destination = CompanyHomeDestination(request.company)
    elif standing.person_slug is not None:
        destination = PersonHomeDestination(standing.person_slug)
    else:
        return _invalid(_NO_PERSON_HOME)
    try:
        view = await asyncio.to_thread(create_project_subject, request.name, destination, request_id=request.request_id)
    except PartialCommitFailure as error:
        return _failed(ConfigFailureKind.PARTIAL_COMMIT, error)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidCandidate, ValueError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done(_view_payload(view))


async def _invite(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.INVITE, instance=request.instance)
    if refused is not None:
        return refused
    assert request.instance is not None
    try:
        outcome = await asyncio.to_thread(invite_person, request.instance)
    except ValueError as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done(
        {"name": outcome.name, "email": outcome.email, "links": outcome.links, "email_sent": outcome.email_sent}
    )


async def _discord_voice_bot(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.BIND_VOICE_BOT, instance=request.instance)
    if refused is not None:
        return refused
    assert request.instance is not None
    try:
        result = await asyncio.to_thread(
            configure_person_discord_voice_bot, request.instance, config.discord.token or _NO_TOKEN
        )
    except (OSError, ValueError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done({"environment_secured": result.environment_secured})


async def _help_desk_links(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.HELP_DESK_LINKS, instance=request.instance)
    if refused is not None:
        return refused
    assert request.kind is not None and request.instance is not None
    kind = request.kind.value
    identifier = DeskIdentifier(_DESK_KIND_BY_SUBJECT[request.kind], request.instance)
    if not config.computer.is_master:
        return _invalid(_DESK_NOT_ON_MASTER)
    if local_desk_endpoint(identifier, config.computer.name, True) is None:
        template = _DESK_NOT_ENABLED if desk_home_present(identifier) else _DESK_NOT_HOSTED
        return _invalid(template.format(kind=kind, slug=request.instance))
    try:
        fleet = await observe_fleet_from_heartbeats()
    except (OSError, RedisError) as error:
        return _invalid(_FLEET_UNOBSERVABLE.format(error=error))
    if not fleet.conversation_entry_safe():
        return _invalid(_FLEET_LAGGING.format(computers=_LIST_SEPARATOR.join(fleet.lacking_conversation_entry())))
    rendered = identifier.render()
    links = await render_help_desk_links(rendered, telegram_allowed=len(rendered) <= TELEGRAM_START_PARAMETER_MAX)
    return _done({"identifier": rendered, "links": links})


async def _validate(_standing: ConfigurationStanding, _request: ConfigRequest) -> ConfigOutcome:
    results = await asyncio.to_thread(validate_all)
    return _done(
        {
            "results": [
                {"area": item.area, "passed": item.passed, "errors": item.errors, "suggestions": item.suggestions}
                for item in results
            ]
        }
    )


async def _env_list(_standing: ConfigurationStanding, _request: ConfigRequest) -> ConfigOutcome:
    statuses = await asyncio.to_thread(check_env_vars)
    return _done(
        {
            "variables": [
                {
                    "name": status.info.name,
                    "service": status.info.adapter,
                    "is_set": status.is_set,
                    "description": status.info.description,
                }
                for status in statuses
            ]
        }
    )


async def _env_set(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    if standing.platform_role == HUMAN_ROLE_CUSTOMER:
        return ConfigOutcome(failure=ConfigFailure(kind=ConfigFailureKind.REFUSED, message=_FORBIDDEN_FOR_CUSTOMER))
    updated: list[str] = []
    for key, value in request.env_pairs:
        if not key or not value:
            continue
        write_environment_value(PROJECT_ENV_PATH, key, value)
        os.environ[key] = value  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
        updated.append(key)
    return _done({"updated": updated})


def _jobs_array_from_view(view: SubjectView) -> list[Mapping[str, object]]:
    section = view.sections.get(_PROJECT_SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(_INVALID_PROJECT_SECTION)
    jobs = section.get(_JOBS_SECTION, [])
    if not isinstance(jobs, list):
        raise ValueError(_INVALID_JOBS_ARRAY)
    entries: list[Mapping[str, object]] = []
    for entry in jobs:
        if not isinstance(entry, Mapping) or any(not isinstance(key, str) for key in entry):
            raise ValueError(_INVALID_JOBS_ARRAY)
        entries.append(cast(Mapping[str, object], entry))
    return entries


async def _job_subscription(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Subscribe the project to a published job, or deactivate its subscription."""
    assert request.instance is not None and request.job is not None
    subject = SubjectRef(ConfigSubjectKind.PROJECT, request.instance)
    refused = _refusal(
        standing,
        request,
        ConfigurationOperation.PATCH,
        instance=request.instance,
        sections=affected_sections(subject, {_JOBS_SECTION: []}),
    )
    if refused is not None:
        return refused
    try:
        view = await asyncio.to_thread(read_subject, subject)
        jobs = _jobs_array_from_view(view)
        plan = plan_job_subscription(jobs, load_global_config().jobs, request.job, request.enabled)
        if plan.jobs is not None:
            await asyncio.to_thread(
                patch_subject,
                subject,
                {_JOBS_SECTION: list(plan.jobs)},
                expected_revision=view.revision,
                request_id=request.request_id,
            )
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except StaleRevision as error:
        return ConfigOutcome(
            failure=ConfigFailure(
                kind=ConfigFailureKind.STALE_REVISION,
                message=str(error),
                expected=str(error.expected),
                actual=str(error.actual),
            )
        )
    except PartialCommitFailure as error:
        return _failed(ConfigFailureKind.PARTIAL_COMMIT, error)
    except (InvalidCandidate, ReadOnlyProjection, ValueError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done({"change": plan.change.value})


_OPERATIONS: Final[Mapping[ConfigVerb, Callable[[ConfigurationStanding, ConfigRequest], Awaitable[ConfigOutcome]]]] = {
    ConfigVerb.LIST: _list,
    ConfigVerb.GET: _get,
    ConfigVerb.INIT: _init,
    ConfigVerb.PATCH: _patch,
    ConfigVerb.REMOVE: _remove,
    ConfigVerb.CREATE: _create,
    ConfigVerb.INVITE: _invite,
    ConfigVerb.DISCORD_VOICE_BOT: _discord_voice_bot,
    ConfigVerb.HELP_DESK_LINKS: _help_desk_links,
    ConfigVerb.VALIDATE: _validate,
    ConfigVerb.ENV_LIST: _env_list,
    ConfigVerb.ENV_SET: _env_set,
    ConfigVerb.JOB_SUBSCRIPTION: _job_subscription,
}


async def run_config_operation(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Run one configuration operation for a caller's standing and answer with its structured outcome."""
    return await _OPERATIONS[request.verb](standing, request)
