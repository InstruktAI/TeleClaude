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
from pathlib import Path
from typing import Final, cast

from redis.exceptions import RedisError

from teleclaude.cli.config_handlers import check_env_vars, validate_all
from teleclaude.closed_model import MASKED_INPUT
from teleclaude.config._environment import (
    CompanyCredentialsError,
    InvalidEnvironmentReferenceError,
    mutate_environment_value,
    write_environment_value,
)
from teleclaude.config.editor_view import (
    current_machine_environment,
    editor_fields,
    editor_revision,
    person_secret_editor_fields,
)
from teleclaude.config.effective_view import (
    InvalidEffectiveValue,
    effective_sections,
    environment_references,
    without_masked_values,
)
from teleclaude.config.field_edit import apply_reference_edit, compile_field_edit
from teleclaude.config.jobs import plan_job_subscription
from teleclaude.config.loader import load_global_config, update_global_environment
from teleclaude.config.machine import config
from teleclaude.config.operation_answers import (
    EditorFieldAnswer,
    EditorInputKind,
    EditorViewAnswer,
    EnvironmentChangeAnswer,
    PersonSecretRow,
    PersonSecretsAnswer,
)
from teleclaude.config.operation_requests import (
    ENVIRONMENT_REFERENCES_KEY,
    INVITE_EMAIL_ENABLED_KEY,
    INVITE_UNAVAILABLE_PROVIDERS_KEY,
    VALIDATE_NOTES_KEY,
    ConfigEditIntent,
    ConfigFailure,
    ConfigFailureKind,
    ConfigOutcome,
    ConfigRequest,
    ConfigVerb,
    Payload,
)
from teleclaude.config.person_secrets import (
    PersonSecretStorageError,
    clear_person_mcp_secret,
    list_person_mcp_secret_inventory,
    replace_person_mcp_secret,
)
from teleclaude.config.person_voice import configure_person_discord_voice_bot
from teleclaude.config.project_subject_init import adopt_project_subject, create_project_subject
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
from teleclaude.config.validation import is_section_available
from teleclaude.config_subjects import ConfigEnvironment, ConfigSubjectKind, SubjectRef
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
from teleclaude.invite import (
    InvitationOwnerUnavailable,
    admit_invitation_here,
    invitation_owner,
    invite_person,
    render_help_desk_links,
)
from teleclaude.paths import PROJECT_ENV_PATH
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.project_setup.init_flow import (
    CompanyHomeDestination,
    PersonHomeDestination,
    PlatformPathDestination,
    ProjectDestination,
)

_DESK_KIND_BY_SUBJECT: Final = {
    ConfigSubjectKind.COMPANY: HelpDeskKind.COMPANY,
    ConfigSubjectKind.PROJECT: HelpDeskKind.PROJECT,
}
_ROLES_FIELD = "roles"
_JSON_MODE: Final = "json"
_NO_PERSON_HOME = "creating in your own home needs a registered person."
_RELATIVE_DESTINATION = "a project destination path must be absolute: {path}"
_DESK_NOT_ENABLED = "help desk of {kind} {slug} is not enabled"
_DESK_NOT_HOSTED = "this computer does not host the help desk of {kind} {slug}"
_DESK_NOT_ON_MASTER = "help desks run on the mesh master, and this computer is not the master"
_FLEET_UNOBSERVABLE = "cannot observe the fleet: {error}"
_FLEET_LAGGING = "help-desk entry is not served until every computer runs it; lagging: {computers}"
_LIST_SEPARATOR = ", "
_DISCORD_SECTION = "discord"
_DISCORD_NOT_ENABLED = "Discord is not enabled on this computer, so there is no bot to bind a voice bot to."
_REFERENCE_KINDS = frozenset({ConfigSubjectKind.COMPUTER, ConfigSubjectKind.GLOBAL, ConfigSubjectKind.PERSON})
# The subject that owns each environment; an environment request is cleared as a patch of it.
_ENVIRONMENT_OWNER: Final = {
    ConfigEnvironment.MACHINE: ConfigSubjectKind.COMPUTER,
    ConfigEnvironment.GLOBAL: ConfigSubjectKind.GLOBAL,
    ConfigEnvironment.PERSON: ConfigSubjectKind.PERSON,
}
_PATCH_FIELDS_REQUIRED = "a patch names its subject kind, the patch, and the revision it was built from"
_INSTANCE_REQUIRED = "this operation names one {kind} instance"
_ENVIRONMENT_PERSON_REQUIRED = "a person's environment request names the person"
_PROJECT_SECTION = "project"
_JOBS_SECTION = "jobs"
_MASTER_SCOPED_KEY = "master_scoped_not_applicable"
_INVALID_PROJECT_SECTION = "Project subject has no writable project section"
_INVALID_JOBS_ARRAY = "Project subject has an invalid jobs array"
_INVOCATION_DIRECTORY_REQUIRED = "project adoption requires the client's invocation directory"
_FIELD_ID_REQUIRED = "a configuration field edit requires its field identity"
_FIELD_REVISION_REQUIRED = "a configuration field edit requires the revision it was built from"
_EDITOR_REVISION_REQUIRED = "a reference-backed field edit requires its editor revision"
_FIELD_EDIT_SUBJECT_REQUIRED = "field edits currently support computer and person configuration subjects"
_FIELD_EDIT_ACTION_REQUIRED = "the field edit intent did not produce an owner action"
_STALE_REVISION_MESSAGE = "the configuration changed since the editor view was read"
_PERSON_SECRET_STORE_UNAVAILABLE = "Personal secret storage is unavailable."
_REQUEST_PATCH_KEY = "patch"
_REQUEST_KIND_KEY = "kind"
_SECRET_UNAVAILABLE_IDENTITY = "secrets.unavailable"
_SECRET_FIELD_LABEL = "Personal MCP secrets"
_SECRET_SECTION_LABEL = "Secrets"


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
        machine_environment = current_machine_environment() if view.ref.kind is ConfigSubjectKind.COMPUTER else None
        sections = effective_sections(view, machine_environment=machine_environment)
        if view.ref.kind in _REFERENCE_KINDS:
            read_only[ENVIRONMENT_REFERENCES_KEY] = [
                entry.model_dump(mode=_JSON_MODE)
                for entry in environment_references(view, machine_environment=machine_environment)
            ]
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidEffectiveValue, InvalidEnvironmentReferenceError, CompanyCredentialsError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done({"view": {**sections, **read_only}, "revision": view.revision})


async def _editor_get(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Return the schema-derived editor projection after the ordinary subject clearance check."""
    refused = _refusal(standing, request, ConfigurationOperation.GET, instance=request.instance)
    if refused is not None:
        return refused
    try:
        view = await asyncio.to_thread(read_subject, _subject_ref(request))
        machine_environment = current_machine_environment() if view.ref.kind is ConfigSubjectKind.COMPUTER else None
        sections = effective_sections(view, machine_environment=machine_environment)
        read_only = dict(view.read_only)
        outside = read_only.get(_MASTER_SCOPED_KEY, [])
        outside_scope = tuple(str(item) for item in outside) if isinstance(outside, list) else ()
        references = environment_references(view, machine_environment=machine_environment)
        fields = editor_fields(
            view.ref.kind,
            sections,
            source_sections=view.sections,
            references=references,
        )
        revision = editor_revision(view, machine_environment=machine_environment)
        secret_store_available: bool | None = None
        if view.ref.kind is ConfigSubjectKind.PERSON and request.instance is not None:
            secrets = await asyncio.to_thread(_person_editor_secret_fields, request.instance)
            secret_store_available = secrets[0]
            fields.extend(secrets[1])
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidEffectiveValue, InvalidEnvironmentReferenceError, CompanyCredentialsError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    answer = EditorViewAnswer(
        fields=fields,
        revision=view.revision,
        editor_revision=revision,
        outside_scope=list(outside_scope),
        secret_store_available=secret_store_available,
    )
    return _done(answer.model_dump(mode=_JSON_MODE))


async def _field_edit(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Apply one schema-addressed editor action through the owning subject operation."""
    if request.kind not in (ConfigSubjectKind.COMPUTER, ConfigSubjectKind.PERSON):
        return _invalid(_FIELD_EDIT_SUBJECT_REQUIRED)
    if request.field_id is None:
        return _invalid(_FIELD_ID_REQUIRED)
    if request.revision is None:
        return _invalid(_FIELD_REVISION_REQUIRED)
    if request.kind is ConfigSubjectKind.PERSON and request.instance is None:
        return _invalid(_INSTANCE_REQUIRED.format(kind=ConfigSubjectKind.PERSON.value))
    refused = _refusal(standing, request, ConfigurationOperation.PATCH, instance=request.instance)
    if refused is not None:
        return refused
    try:
        view = await asyncio.to_thread(read_subject, _subject_ref(request))
        machine_environment = current_machine_environment() if view.ref.kind is ConfigSubjectKind.COMPUTER else None
        references = environment_references(view, machine_environment=machine_environment)
        fields = editor_fields(
            view.ref.kind,
            effective_sections(view, machine_environment=machine_environment),
            source_sections=view.sections,
            references=references,
        )
        if view.ref.kind is ConfigSubjectKind.PERSON and request.instance is not None:
            fields.extend(_person_editor_secret_fields(request.instance)[1])
        plan = compile_field_edit(
            view,
            fields,
            references,
            request.field_id,
            request.edit_intent,
            request.value,
        )
        if plan.reference is not None:
            if request.editor_revision is None:
                return _invalid(_EDITOR_REVISION_REQUIRED)
            if request.edit_intent is None:
                return _invalid(_FIELD_EDIT_ACTION_REQUIRED)
            await asyncio.to_thread(
                apply_reference_edit,
                view.ref,
                request.field_id,
                request.edit_intent,
                request.value,
                request.editor_revision,
            )
        elif plan.unchanged or request.edit_intent is ConfigEditIntent.KEEP:
            if request.revision != view.revision:
                return _stale_revision(request.revision, view.revision)
        else:
            if plan.patch is None:
                return _invalid(_FIELD_EDIT_ACTION_REQUIRED)
            outcome = await _patch(
                standing,
                request.model_copy(update={_REQUEST_PATCH_KEY: plan.patch}),
            )
            if outcome.failure is not None:
                return outcome
        return await _editor_get(
            standing,
            ConfigRequest(
                verb=ConfigVerb.EDITOR_GET,
                kind=request.kind,
                instance=request.instance,
                request_id=request.request_id,
            ),
        )
    except StaleRevision as error:
        return _stale_revision(str(error.expected), str(error.actual))
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidCandidate, ReadOnlyProjection, PersonSecretStorageError, OSError, ValueError) as error:
        return _failed(ConfigFailureKind.INVALID, error)


def _stale_revision(expected: str, actual: str) -> ConfigOutcome:
    return ConfigOutcome(
        failure=ConfigFailure(
            kind=ConfigFailureKind.STALE_REVISION,
            message=_STALE_REVISION_MESSAGE,
            expected=expected,
            actual=actual,
        )
    )


def _person_editor_secret_fields(instance: str) -> tuple[bool, list[EditorFieldAnswer]]:
    """Project the existing registry-derived secret inventory into editor rows."""
    try:
        inventory = list_person_mcp_secret_inventory(instance)
    except (OSError, PersonSecretStorageError):
        return False, [
            EditorFieldAnswer(
                identity=_SECRET_UNAVAILABLE_IDENTITY,
                label=_SECRET_FIELD_LABEL,
                value=None,
                input_kind=EditorInputKind.STRING,
                section=_SECRET_SECTION_LABEL,
                editable=False,
                available=False,
                description=_PERSON_SECRET_STORE_UNAVAILABLE,
            )
        ]
    return True, person_secret_editor_fields(inventory)


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
    if request.kind is None or request.patch is None or request.revision is None:
        return _invalid(_PATCH_FIELDS_REQUIRED)
    ref = _subject_ref(request)
    patch = without_masked_values(request.kind, request.patch)
    try:
        sections = affected_sections(ref, patch)
    except (InvalidCandidate, ReadOnlyProjection) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    refused = _refusal(
        standing,
        request,
        ConfigurationOperation.PATCH,
        instance=request.instance,
        sections=sections,
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


async def _project_adopt(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Adopt the project rooted at the invocation directory under target clearance."""
    if request.invocation_cwd is None:
        return _invalid(_INVOCATION_DIRECTORY_REQUIRED)
    refused = _refusal(standing, request, ConfigurationOperation.ADOPT, instance=None)
    if refused is not None:
        return refused
    try:
        adoption_root = resolve_invocation_roots(request.invocation_cwd).adoption_root()
        view = await asyncio.to_thread(adopt_project_subject, adoption_root, request_id=request.request_id)
    except PartialCommitFailure as error:
        return _failed(ConfigFailureKind.PARTIAL_COMMIT, error)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (InvalidCandidate, ValueError, FileNotFoundError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done(_view_payload(view))


async def _invitation_destination(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Ask the invitation owner for the unique live master after clearance for the person invite."""
    if request.instance is None:
        return _invalid(_INSTANCE_REQUIRED.format(kind=ConfigSubjectKind.PERSON.value))
    owner_request = request.model_copy(update={_REQUEST_KIND_KEY: ConfigSubjectKind.PERSON})
    refused = _refusal(standing, owner_request, ConfigurationOperation.INVITE, instance=request.instance)
    if refused is not None:
        return refused
    try:
        owner = invitation_owner(await observe_fleet_from_heartbeats())
    except InvitationOwnerUnavailable as error:
        return _failed(ConfigFailureKind.REFUSED, error)
    except (OSError, RedisError) as error:
        return _invalid(_FLEET_UNOBSERVABLE.format(error=error))
    return _done({ConfigSubjectKind.COMPUTER.value: owner})


async def _invite(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.INVITE, instance=request.instance)
    if refused is not None:
        return refused
    assert request.instance is not None
    try:
        admit_invitation_here(await observe_fleet_from_heartbeats())
    except InvitationOwnerUnavailable as error:
        return _failed(ConfigFailureKind.REFUSED, error)
    except (OSError, RedisError) as error:
        return _invalid(_FLEET_UNOBSERVABLE.format(error=error))
    try:
        outcome = await asyncio.to_thread(invite_person, request.instance)
    except ValueError as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done(
        {
            "name": outcome.name,
            "email": outcome.email,
            "links": outcome.links,
            "email_sent": outcome.email_sent,
            INVITE_EMAIL_ENABLED_KEY: outcome.email_enabled,
            INVITE_UNAVAILABLE_PROVIDERS_KEY: list(outcome.unavailable_providers),
        }
    )


async def _discord_voice_bot(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    refused = _refusal(standing, request, ConfigurationOperation.BIND_VOICE_BOT, instance=request.instance)
    if refused is not None:
        return refused
    assert request.instance is not None
    discord_token = config.discord.token
    if discord_token is None or not is_section_available(_DISCORD_SECTION, config):
        return ConfigOutcome(failure=ConfigFailure(kind=ConfigFailureKind.REFUSED, message=_DISCORD_NOT_ENABLED))
    try:
        result = await asyncio.to_thread(configure_person_discord_voice_bot, request.instance, discord_token)
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
    if not config.master_scope_applies():
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
                {
                    "area": item.area,
                    "passed": item.passed,
                    "errors": item.errors,
                    "suggestions": item.suggestions,
                    VALIDATE_NOTES_KEY: item.notes,
                }
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
                    "applicable": config.scope_applies(status.info.path),
                }
                for status in statuses
            ]
        }
    )


def _environment_refusal(
    standing: ConfigurationStanding, request: ConfigRequest, environment: ConfigEnvironment
) -> ConfigOutcome | None:
    """Clearance for changing an environment: as a patch of the subject that owns it."""
    owner = request.model_copy(update=dict(kind=_ENVIRONMENT_OWNER[environment]))
    instance = request.instance if environment is ConfigEnvironment.PERSON else None
    return _refusal(standing, owner, ConfigurationOperation.PATCH, instance=instance)


def _apply_environment(request: ConfigRequest, environment: ConfigEnvironment) -> EnvironmentChangeAnswer:
    """Set and clear the request's variables in the one environment it names."""
    updated: list[str] = []
    cleared: list[str] = []
    for key, value in request.env_pairs:
        if not key or not value or value == MASKED_INPUT:
            continue
        _set_environment_value(request, environment, key, value)
        updated.append(key)
    for key in request.env_clear:
        _clear_environment_value(request, environment, key)
        cleared.append(key)
    return EnvironmentChangeAnswer(updated=updated, cleared=cleared)


def _set_environment_value(request: ConfigRequest, environment: ConfigEnvironment, key: str, value: str) -> None:
    match environment:
        case ConfigEnvironment.MACHINE:
            write_environment_value(PROJECT_ENV_PATH, key, value)
            os.environ[key] = value  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
        case ConfigEnvironment.GLOBAL:
            update_global_environment(key, value)
        case ConfigEnvironment.PERSON:
            assert request.instance is not None
            replace_person_mcp_secret(request.instance, key, value)


def _clear_environment_value(request: ConfigRequest, environment: ConfigEnvironment, key: str) -> None:
    match environment:
        case ConfigEnvironment.MACHINE:
            mutate_environment_value(PROJECT_ENV_PATH, key, None)
            os.environ.pop(key, None)  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
        case ConfigEnvironment.GLOBAL:
            update_global_environment(key, None)
        case ConfigEnvironment.PERSON:
            assert request.instance is not None
            clear_person_mcp_secret(request.instance, key)


async def _env_set(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    environment = request.environment or ConfigEnvironment.MACHINE
    if environment is ConfigEnvironment.PERSON and request.instance is None:
        return _invalid(_ENVIRONMENT_PERSON_REQUIRED)
    refused = _environment_refusal(standing, request, environment)
    if refused is not None:
        return refused
    try:
        if environment is ConfigEnvironment.PERSON and request.instance is not None:
            await asyncio.to_thread(read_subject, SubjectRef(ConfigSubjectKind.PERSON, request.instance))
        answer = await asyncio.to_thread(_apply_environment, request, environment)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except (OSError, ValueError, PersonSecretStorageError) as error:
        return _failed(ConfigFailureKind.INVALID, error)
    return _done(answer.model_dump(mode=_JSON_MODE))


async def _person_secrets(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """The registry-derived inventory of a person's personal MCP secrets: names and set state, never values."""
    if request.instance is None:
        return _invalid(_INSTANCE_REQUIRED.format(kind=ConfigSubjectKind.PERSON.value))
    owner = request.model_copy(update=dict(kind=ConfigSubjectKind.PERSON))
    refused = _refusal(standing, owner, ConfigurationOperation.GET, instance=request.instance)
    if refused is not None:
        return refused
    try:
        await asyncio.to_thread(read_subject, SubjectRef(ConfigSubjectKind.PERSON, request.instance))
        statuses = await asyncio.to_thread(list_person_mcp_secret_inventory, request.instance)
    except SubjectNotFound as error:
        return _failed(ConfigFailureKind.NOT_FOUND, error)
    except PersonSecretStorageError:
        return _done(PersonSecretsAnswer(available=False).model_dump(mode=_JSON_MODE))
    answer = PersonSecretsAnswer(
        available=True,
        secrets=[
            PersonSecretRow(name=status.name, is_set=status.is_set, requiring_servers=list(status.requiring_servers))
            for status in statuses
        ],
    )
    return _done(answer.model_dump(mode=_JSON_MODE))


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
    ConfigVerb.EDITOR_GET: _editor_get,
    ConfigVerb.FIELD_EDIT: _field_edit,
    ConfigVerb.PROJECT_ADOPT: _project_adopt,
    ConfigVerb.INVITATION_DESTINATION: _invitation_destination,
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
    ConfigVerb.PERSON_SECRETS: _person_secrets,
    ConfigVerb.JOB_SUBSCRIPTION: _job_subscription,
}


async def run_config_operation(standing: ConfigurationStanding, request: ConfigRequest) -> ConfigOutcome:
    """Run one configuration operation for a caller's standing and answer with its structured outcome."""
    return await _OPERATIONS[request.verb](standing, request)
