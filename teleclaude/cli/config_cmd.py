"""Kind-addressed configuration command adapters, cleared in-process.

Every invocation: mint a request_id, gate on the verb band
(`require_cli_clearance`), resolve the caller's standing, decide target
clearance (`configuration_clearance.decide`), then call the matching
`teleclaude.config.resources` verb. A refusal at either gate prints no view
and exits non-zero before any configuration is read.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO, cast

import yaml
from redis.exceptions import RedisError

from teleclaude.cli.session_auth import ResolvedCliIdentity, resolve_cli_identity
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import address_computer, addressed_computer, explicit_computer
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _maybe_show_help
from teleclaude.cli.telec.surface import (
    CONFIG_COMPANY_GET,
    CONFIG_COMPANY_HELP_DESK_LINKS,
    CONFIG_COMPANY_INIT,
    CONFIG_COMPANY_LIST,
    CONFIG_COMPANY_PATCH,
    CONFIG_COMPUTER_GET,
    CONFIG_COMPUTER_INIT,
    CONFIG_COMPUTER_LIST,
    CONFIG_COMPUTER_PATCH,
    CONFIG_GLOBAL_GET,
    CONFIG_GLOBAL_INIT,
    CONFIG_GLOBAL_LIST,
    CONFIG_GLOBAL_PATCH,
    CONFIG_PERSON_DISCORD_VOICE_BOT,
    CONFIG_PERSON_GET,
    CONFIG_PERSON_INIT,
    CONFIG_PERSON_INVITE,
    CONFIG_PERSON_LIST,
    CONFIG_PERSON_PATCH,
    CONFIG_PROJECT_ADOPT,
    CONFIG_PROJECT_CREATE,
    CONFIG_PROJECT_GET,
    CONFIG_PROJECT_HELP_DESK_LINKS,
    CONFIG_PROJECT_LIST,
    CONFIG_PROJECT_PATCH,
)
from teleclaude.config.project_subject_init import adopt_project_subject
from teleclaude.config.resource_contract import InvalidCandidate, PartialCommitFailure, SubjectNotFound, SubjectView
from teleclaude.config.subject_operations import (
    INVITE_UNAVAILABLE_PROVIDERS_KEY,
    ConfigFailureKind,
    ConfigOutcome,
    ConfigRequest,
    ConfigVerb,
    run_config_operation,
)
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.core.configuration_clearance import (
    ConfigurationOperation,
    ConfigurationTarget,
    ProjectCreationForm,
    decide,
    standing_for,
)
from teleclaude.core.inbound.fleet import observe_fleet_from_heartbeats
from teleclaude.invite import InvitationOwnerUnavailable, invitation_owner
from teleclaude.project_root import resolve_invocation_cwd, resolve_invocation_roots

_YAML = "yaml"
_JSON = "json"
_FORMAT_ERROR = "Error: Invalid output format: {format} (must be yaml or json)"
_UNEXPECTED_ARGUMENT_ERROR = "Error: Unexpected argument: {argument}"
_MISSING_PATCH_ERROR = "Error: No patch provided. Use --yaml, --from-file, or pipe YAML to stdin."
_PATCH_MAPPING_ERROR = "Error: Patch must be a YAML mapping."
_PATH_NOT_FOUND_ERROR = "Path not found: {path} (missing '{segment}')"
_ERRORS_HEADING = "Errors encountered:"
_ERROR_ROW = "  {error}"
_MISSING_REVISION_ERROR = "Error: --revision is required."
_MISSING_INSTANCE_ERROR = "Error: {kind} requires an instance slug as the first argument."
_UNKNOWN_VERB_ERROR = "Error: Unknown config {kind} verb: {verb}"
_REQUEST_SUFFIX = " (request {request_id})"
_REFUSED_MESSAGE = "Error: refused — required standing: {required_standing} ({reason}){request}"
_STALE_MESSAGE = "Error: stale revision — expected {expected}, subject is now at {actual}{request}"
_NOT_FOUND_MESSAGE = "Error: {message}{request}"
_INVALID_MESSAGE = "Error: {message}{request}"
_PARTIAL_COMMIT_MESSAGE = (
    "Error: {message}{request}\nThe affected files may be in a mixed state — read them back before retrying."
)
_PROJECT_CREATE_COMPLETE = "telec config project create complete."
_PROJECT_ADOPT_COMPLETE = "telec config project adopt complete."
_KIND_USAGE = "Usage: telec config {kind} <{verbs}>"
_INIT_KIND_VERBS = "list|get|init|patch"
_PROJECT_VERBS = "list|get|create|adopt|patch"
_INIT_VERB = "init"
_CREATE_VERB = "create"
_ADOPT_VERB = "adopt"
_CREATE_USAGE_ERROR = (
    "Error: project create takes exactly one name: telec config project create <name> [--company <slug> | --path <dir>]"
)
_CREATE_FORM_CONFLICT_ERROR = "Error: --company and --path never combine."
_NO_PERSON_HOME_ERROR = "Error: creating in your own home needs a registered person."
_SLUG_FIELD = "slug"
_HELP_DESK_LINKS_VERB = "help-desk-links"
# The keys of the help-desk links JSON answer.
_LINKS_IDENTIFIER_KEY = "identifier"
_LINKS_KEY = "links"
_LINKS_REQUEST_ID_KEY = "request_id"
_INVITE_FLEET_UNOBSERVABLE = "cannot observe the fleet to find the invitation owner: {error}"
_UNAVAILABLE_PROVIDERS_LINE = "Unavailable for this invitation: {providers}"
_PROVIDER_SEPARATOR = ", "
_NO_LINKS_LINE = "No entry links could be generated for {identifier}."
_LINK_LINE = "  {adapter}: {link}"
_LINKS_HEADING = "Entry links for {identifier}:"
_OPERATIONS_PATH = "/config/operations"
_JSON_MODE = "json"
_PLAIN_ERROR = "Error: {message}"
_INSTANCES_KEY = "instances"
_VIEW_KEY = "view"
_SECTIONS_KEY = "sections"
_REVISION_KEY = "revision"

_KIND_TO_SUBJECT: dict[str, ConfigSubjectKind] = {
    "computer": ConfigSubjectKind.COMPUTER,
    "global": ConfigSubjectKind.GLOBAL,
    "person": ConfigSubjectKind.PERSON,
    "company": ConfigSubjectKind.COMPANY,
    "project": ConfigSubjectKind.PROJECT,
}
_SINGLETON_KINDS = frozenset({ConfigSubjectKind.COMPUTER, ConfigSubjectKind.GLOBAL})

_LIST_COMMAND_DEFS = {
    "computer": CONFIG_COMPUTER_LIST,
    "global": CONFIG_GLOBAL_LIST,
    "person": CONFIG_PERSON_LIST,
    "company": CONFIG_COMPANY_LIST,
    "project": CONFIG_PROJECT_LIST,
}
_GET_COMMAND_DEFS = {
    "computer": CONFIG_COMPUTER_GET,
    "global": CONFIG_GLOBAL_GET,
    "person": CONFIG_PERSON_GET,
    "company": CONFIG_COMPANY_GET,
    "project": CONFIG_PROJECT_GET,
}
_INIT_COMMAND_DEFS = {
    "computer": CONFIG_COMPUTER_INIT,
    "global": CONFIG_GLOBAL_INIT,
    "person": CONFIG_PERSON_INIT,
    "company": CONFIG_COMPANY_INIT,
}
_PATCH_COMMAND_DEFS = {
    "computer": CONFIG_COMPUTER_PATCH,
    "global": CONFIG_GLOBAL_PATCH,
    "person": CONFIG_PERSON_PATCH,
    "company": CONFIG_COMPANY_PATCH,
    "project": CONFIG_PROJECT_PATCH,
}


def handle_config_kind_command(kind: str, args: list[str]) -> None:
    """Dispatch one `telec config <kind> <verb>` invocation."""
    if _maybe_show_help("config", [kind, *args]):
        return
    subject_kind = _KIND_TO_SUBJECT.get(kind)
    if subject_kind is None:
        print(f"Error: Unknown config kind: {kind}")
        raise SystemExit(1)
    if not args:
        verbs = _PROJECT_VERBS if subject_kind is ConfigSubjectKind.PROJECT else _INIT_KIND_VERBS
        print(_KIND_USAGE.format(kind=kind, verbs=verbs))
        raise SystemExit(1)
    verb, verb_args = args[0], args[1:]
    request_id = str(uuid.uuid4())

    if verb == "list":
        _handle_list(kind, subject_kind, verb_args, request_id)
    elif verb == "get":
        _handle_get(kind, subject_kind, verb_args, request_id)
    elif verb == _INIT_VERB and subject_kind is not ConfigSubjectKind.PROJECT:
        _handle_init(kind, subject_kind, verb_args, request_id)
    elif verb == "patch":
        _handle_patch(kind, subject_kind, verb_args, request_id)
    elif verb == _CREATE_VERB and subject_kind is ConfigSubjectKind.PROJECT:
        _handle_create(verb_args, request_id)
    elif verb == _ADOPT_VERB and subject_kind is ConfigSubjectKind.PROJECT:
        _handle_adopt(verb_args, request_id)
    elif verb == "invite" and subject_kind is ConfigSubjectKind.PERSON:
        _handle_invite(verb_args, request_id)
    elif verb == "discord-voice-bot" and subject_kind is ConfigSubjectKind.PERSON:
        _handle_discord_voice_bot(verb_args, request_id)
    elif verb == _HELP_DESK_LINKS_VERB and subject_kind in _HELP_DESK_LINKS_COMMAND_DEFS:
        _handle_help_desk_links(kind, subject_kind, verb_args, request_id)
    else:
        print(_UNKNOWN_VERB_ERROR.format(kind=kind, verb=verb))
        raise SystemExit(1)


# --- Shared gate ---


def _gate(
    kind: str,
    verb: str,
    subject_kind: ConfigSubjectKind,
    *,
    instance: str | None,
    operation: ConfigurationOperation,
    sections: frozenset[str],
    request_id: str,
    creation_form: ProjectCreationForm | None = None,
) -> ResolvedCliIdentity:
    """Verb band, then target clearance. Refuses and exits before any config is read."""
    identity = resolve_cli_identity()
    standing = standing_for(identity)
    target = ConfigurationTarget(
        kind=subject_kind,
        instance=instance,
        operation=operation,
        sections=sections,
        creation_form=creation_form,
    )
    decision = decide(standing, target, request_id=request_id)
    if not decision.allowed:
        print(
            _REFUSED_MESSAGE.format(
                required_standing=decision.required_standing.value,
                reason=decision.reason,
                request=_REQUEST_SUFFIX.format(request_id=request_id),
            )
        )
        raise SystemExit(1)
    return identity


def _require_instance(
    kind: str, subject_kind: ConfigSubjectKind, positionals: tuple[str, ...]
) -> tuple[str | None, tuple[str, ...]]:
    """Split a leading instance slug off `positionals` for instance-addressed kinds."""
    if subject_kind in _SINGLETON_KINDS:
        return None, positionals
    if not positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind=kind))
        raise SystemExit(1)
    return positionals[0], positionals[1:]


# --- performing an operation: here, or on the computer the command addresses ---


def _perform(request: ConfigRequest) -> ConfigOutcome:
    """Run one configuration operation in this process, or ask the addressed computer to run it."""
    if addressed_computer() is not None:
        from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - remote path: daemon API client.

        answer = tool_api_call("POST", _OPERATIONS_PATH, json_body=request.model_dump(mode=_JSON_MODE), timeout=60.0)
        return ConfigOutcome.model_validate(answer)
    standing = standing_for(resolve_cli_identity())
    return asyncio.run(run_config_operation(standing, request))


def _succeeded(
    outcome: ConfigOutcome, request_id: str, errors_to: TextIO
) -> dict[str, object]:  # guard: loose-dict - config payload
    """The operation's payload, or the operation's failure presented and the command exited."""
    failure = outcome.failure
    if failure is None:
        assert outcome.payload is not None
        return outcome.payload
    suffix = _REQUEST_SUFFIX.format(request_id=request_id)
    if failure.kind is ConfigFailureKind.REFUSED and failure.required_standing is not None:
        print(
            _REFUSED_MESSAGE.format(
                required_standing=failure.required_standing, reason=failure.message, request=suffix
            ),
            file=errors_to,
        )
    elif failure.kind is ConfigFailureKind.REFUSED:
        print(_PLAIN_ERROR.format(message=failure.message), file=errors_to)
    elif failure.kind is ConfigFailureKind.STALE_REVISION:
        print(_STALE_MESSAGE.format(expected=failure.expected, actual=failure.actual, request=suffix), file=errors_to)
    elif failure.kind is ConfigFailureKind.NOT_FOUND:
        print(_NOT_FOUND_MESSAGE.format(message=failure.message, request=suffix), file=errors_to)
    elif failure.kind is ConfigFailureKind.PARTIAL_COMMIT:
        print(_PARTIAL_COMMIT_MESSAGE.format(message=failure.message, request=suffix), file=errors_to)
    else:
        print(_INVALID_MESSAGE.format(message=failure.message, request=suffix), file=errors_to)
    raise SystemExit(1)


def run_config_request(
    request: ConfigRequest, *, errors_to: TextIO = sys.stdout
) -> dict[str, object]:  # guard: loose-dict - config payload
    """Perform one operation and return its payload, exiting non-zero on its failure."""
    return _succeeded(_perform(request), request.request_id, errors_to)


# --- list ---


def _handle_list(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parse_command_args(_LIST_COMMAND_DEFS[kind], args)
    payload = run_config_request(ConfigRequest(verb=ConfigVerb.LIST, kind=subject_kind, request_id=request_id))
    instances = cast(list[str | None], payload[_INSTANCES_KEY])
    if not instances:
        print(f"No {kind} subjects.")
        return
    for instance in instances:
        print(instance if instance is not None else f"({kind})")


# --- get ---


def _handle_get(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_GET_COMMAND_DEFS[kind], args)
    instance, paths = _require_instance(kind, subject_kind, parsed.positionals)
    output_format = _output_format(parsed.value(F.FLAG_CONFIG_FORMAT))
    payload = run_config_request(
        ConfigRequest(verb=ConfigVerb.GET, kind=subject_kind, instance=instance, request_id=request_id)
    )
    merged = cast(dict[str, object], payload[_VIEW_KEY])  # guard: loose-dict - heterogeneous rendered config view
    rendered = _select_subject_paths(merged, kind, list(paths)) if paths else merged
    _render({**rendered, "revision": payload[_REVISION_KEY], "request_id": request_id}, output_format)


# --- init ---


def _render_view(
    payload: Mapping[str, object], output_format: str, request_id: str, completion_line: str | None = None
) -> None:
    """Render the view an operation answered with, after its completion line if it has one."""
    if completion_line is not None:
        print(completion_line)
    sections = cast(dict[str, object], payload[_SECTIONS_KEY])  # guard: loose-dict - heterogeneous config sections
    _render({**sections, "revision": payload[_REVISION_KEY], "request_id": request_id}, output_format)


def _handle_init(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_INIT_COMMAND_DEFS[kind], args)
    output_format = _output_format(None)

    if subject_kind in _SINGLETON_KINDS:
        payload = run_config_request(ConfigRequest(verb=ConfigVerb.INIT, kind=subject_kind, request_id=request_id))
        _render_view(payload, output_format, request_id)
        return

    # person / company: fields come from init flags, not from an instance the
    # caller has not yet named (a brand-new person/company has no slug until
    # the engine derives or the caller supplies one).
    if not parsed.positionals:
        print(f"Error: {kind} init requires a name.")
        raise SystemExit(1)
    name = parsed.positionals[0]
    company_slug = parsed.value(F.FLAG_COMPANY_SLUG) if subject_kind is ConfigSubjectKind.COMPANY else None
    fields: dict[str, object] = {"name": name}  # guard: loose-dict - per-kind init payload, passed through as-is
    if subject_kind is ConfigSubjectKind.PERSON:
        email = parsed.value(F.FLAG_PEOPLE_EMAIL)
        if not email:
            print("Error: person init requires --email.")
            raise SystemExit(1)
        fields["email"] = email
        for key, flag in (
            ("slug", F.FLAG_PEOPLE_SLUG),
            ("role", F.FLAG_PEOPLE_ROLE),
            ("username", F.FLAG_PEOPLE_USERNAME),
        ):
            value = parsed.value(flag)
            if value is not None:
                fields[key] = value
    else:
        if company_slug is not None:
            fields[_SLUG_FIELD] = company_slug
    payload = run_config_request(
        ConfigRequest(verb=ConfigVerb.INIT, kind=subject_kind, fields=fields, request_id=request_id)
    )
    _render_view(payload, output_format, request_id)


# --- create and adopt ---


def _handle_create(args: list[str], request_id: str) -> None:
    parsed = parse_command_args(CONFIG_PROJECT_CREATE, args)
    if len(parsed.positionals) != 1:
        print(_CREATE_USAGE_ERROR)
        raise SystemExit(1)
    name = parsed.positionals[0]
    company = parsed.value(F.FLAG_PROJECT_COMPANY)
    path = parsed.value(F.FLAG_PROJECT_PATH)
    if company is not None and path is not None:
        print(_CREATE_FORM_CONFLICT_ERROR)
        raise SystemExit(1)
    if path is not None:
        requested = Path(path).expanduser()
        if not requested.is_absolute() and addressed_computer() is None:
            path = str(resolve_invocation_cwd() / requested)
    payload = run_config_request(
        ConfigRequest(
            verb=ConfigVerb.CREATE,
            kind=ConfigSubjectKind.PROJECT,
            name=name,
            company=company,
            path=path,
            request_id=request_id,
        )
    )
    _render_view(payload, _output_format(None), request_id, _PROJECT_CREATE_COMPLETE)


def _run_init(
    compute: Callable[[], SubjectView],
    output_format: str,
    request_id: str,
    *,
    completion_line: str | None = None,
) -> None:
    """Run one in-process init call, rendering its view or a clean error for every typed refusal."""
    try:
        view = compute()
    except PartialCommitFailure as error:
        print(_PARTIAL_COMMIT_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    except SubjectNotFound as error:
        print(_NOT_FOUND_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    except (InvalidCandidate, ValueError) as error:
        print(_INVALID_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    if completion_line is not None:
        print(completion_line)
    _render({**view.sections, "revision": view.revision, "request_id": request_id}, output_format)


def _handle_adopt(args: list[str], request_id: str) -> None:
    parsed = parse_command_args(CONFIG_PROJECT_ADOPT, args)
    if parsed.positionals:
        print(_UNEXPECTED_ARGUMENT_ERROR.format(argument=parsed.positionals[0]))
        raise SystemExit(1)
    adoption_root = resolve_invocation_roots().adoption_root()
    _gate(
        ConfigSubjectKind.PROJECT.value,
        _ADOPT_VERB,
        ConfigSubjectKind.PROJECT,
        instance=None,
        operation=ConfigurationOperation.ADOPT,
        sections=frozenset(),
        request_id=request_id,
    )
    _run_init(
        lambda: adopt_project_subject(adoption_root, request_id=request_id),
        _output_format(None),
        request_id,
        completion_line=_PROJECT_ADOPT_COMPLETE,
    )


# --- patch ---


def _handle_patch(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_PATCH_COMMAND_DEFS[kind], args)
    instance, rest = _require_instance(kind, subject_kind, parsed.positionals)
    if rest:
        print(_UNEXPECTED_ARGUMENT_ERROR.format(argument=rest[0]))
        raise SystemExit(1)
    output_format = _output_format(parsed.value(F.FLAG_CONFIG_FORMAT))
    revision = parsed.value(F.FLAG_CONFIG_REVISION)
    if not revision:
        print(_MISSING_REVISION_ERROR)
        raise SystemExit(1)
    remove = subject_kind is ConfigSubjectKind.PERSON and parsed.has(F.FLAG_CONFIG_REMOVE)

    if remove:
        assert instance is not None
        removed = run_config_request(
            ConfigRequest(
                verb=ConfigVerb.REMOVE,
                kind=subject_kind,
                instance=instance,
                delete_dir=parsed.has(F.FLAG_PEOPLE_DELETE_DIR),
                request_id=request_id,
            )
        )
        _render({**removed, "request_id": request_id}, output_format)
        return

    patch = _read_patch(parsed.value(F.FLAG_CONFIG_FROM_FILE), parsed.value(F.FLAG_CONFIG_YAML))
    payload = run_config_request(
        ConfigRequest(
            verb=ConfigVerb.PATCH,
            kind=subject_kind,
            instance=instance,
            patch=patch,
            revision=revision,
            request_id=request_id,
        )
    )
    _render_view(payload, output_format, request_id)


# --- person invite / discord-voice-bot ---


def _address_invitation_owner() -> None:
    """With no computer named, address the invitation to the mesh master, or stop when there is none.

    An explicit selection, this computer's own name and the local sentinel included, is kept as
    given: the executing computer admits or refuses it. Selection only picks the destination for
    an omitted one, and nothing is sent or issued while no owner can be named.
    """
    if explicit_computer() is not None:
        return
    try:
        owner = invitation_owner(asyncio.run(observe_fleet_from_heartbeats()))
    except InvitationOwnerUnavailable as error:
        print(_PLAIN_ERROR.format(message=error))
        raise SystemExit(1) from error
    except (OSError, RedisError) as error:
        print(_PLAIN_ERROR.format(message=_INVITE_FLEET_UNOBSERVABLE.format(error=error)))
        raise SystemExit(1) from error
    address_computer(owner)


def _handle_invite(args: list[str], request_id: str) -> None:
    parsed = parse_command_args(CONFIG_PERSON_INVITE, args)
    if not parsed.positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind="person"))
        raise SystemExit(1)
    slug = parsed.positionals[0]
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    _address_invitation_owner()
    outcome = run_config_request(
        ConfigRequest(verb=ConfigVerb.INVITE, kind=ConfigSubjectKind.PERSON, instance=slug, request_id=request_id)
    )
    if use_json:
        print(json.dumps({**outcome, "request_id": request_id}))
        return
    name = outcome["name"]
    links = cast(dict[str, str], outcome["links"])
    if outcome["email_sent"]:
        print(f"Invite sent to {outcome['email']} for {name}{_REQUEST_SUFFIX.format(request_id=request_id)}")
    else:
        available = {platform: url for platform, url in links.items() if url}
        if available:
            relay = "\n".join(f"  {platform}: {url}" for platform, url in available.items())
            print(f"Invite for {name}: email not delivered — share these links directly:\n{relay}")
        else:
            print(f"Invite for {name}: email not delivered and no invite links could be generated.")
    unavailable = cast(list[str], outcome.get(INVITE_UNAVAILABLE_PROVIDERS_KEY) or [])
    if unavailable:
        print(_UNAVAILABLE_PROVIDERS_LINE.format(providers=_PROVIDER_SEPARATOR.join(unavailable)))


def _handle_discord_voice_bot(args: list[str], request_id: str) -> None:
    parsed = parse_command_args(CONFIG_PERSON_DISCORD_VOICE_BOT, args)
    if not parsed.positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind="person"))
        raise SystemExit(1)
    slug = parsed.positionals[0]
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    result = run_config_request(
        ConfigRequest(
            verb=ConfigVerb.DISCORD_VOICE_BOT, kind=ConfigSubjectKind.PERSON, instance=slug, request_id=request_id
        )
    )
    fields = ["discord_voice_bot"]
    if result["environment_secured"]:
        fields.append("personal_env_permissions")
    if use_json:
        print(json.dumps({"ok": True, "slug": slug, "updated": fields, "request_id": request_id}))
    else:
        print(f"Updated {slug}: {', '.join(fields)}.{_REQUEST_SUFFIX.format(request_id=request_id)}")


# --- company / project help-desk-links ---

_HELP_DESK_LINKS_COMMAND_DEFS = {
    ConfigSubjectKind.COMPANY: CONFIG_COMPANY_HELP_DESK_LINKS,
    ConfigSubjectKind.PROJECT: CONFIG_PROJECT_HELP_DESK_LINKS,
}


def _handle_help_desk_links(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_HELP_DESK_LINKS_COMMAND_DEFS[subject_kind], args)
    if not parsed.positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind=kind))
        raise SystemExit(1)
    slug = parsed.positionals[0]
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    answer = run_config_request(
        ConfigRequest(verb=ConfigVerb.HELP_DESK_LINKS, kind=subject_kind, instance=slug, request_id=request_id)
    )
    rendered = cast(str, answer[_LINKS_IDENTIFIER_KEY])
    links = cast(dict[str, str], answer[_LINKS_KEY])
    if use_json:
        print(json.dumps({_LINKS_IDENTIFIER_KEY: rendered, _LINKS_KEY: links, _LINKS_REQUEST_ID_KEY: request_id}))
        return
    available = {adapter: link for adapter, link in links.items() if link}
    if not available:
        print(_NO_LINKS_LINE.format(identifier=rendered))
        return
    print(_LINKS_HEADING.format(identifier=rendered))
    for adapter, link in available.items():
        print(_LINK_LINE.format(adapter=adapter, link=link))


# --- rendering (shared across verbs) ---


def _output_format(value: str | None) -> str:
    """Validate the declared command output format."""
    output_format = value.lower() if value is not None else _YAML
    if output_format not in (_YAML, _JSON):
        print(_FORMAT_ERROR.format(format=output_format))
        raise SystemExit(1)
    return output_format


def _read_patch(
    from_file: str | None, patch_yaml: str | None
) -> dict[str, object]:  # guard: loose-dict - caller-supplied RFC 7386 patch document
    """Read one command-supplied YAML patch without touching the addressed document."""
    if from_file is not None:
        source = Path(from_file).expanduser().resolve()
        content = source.read_text(encoding="utf-8")
    elif patch_yaml is not None:
        content = patch_yaml
    else:
        if sys.stdin.isatty():
            print(_MISSING_PATCH_ERROR)
            raise SystemExit(1)
        content = sys.stdin.read()
    parsed: Any = yaml.safe_load(content)
    if not isinstance(parsed, dict):
        print(_PATCH_MAPPING_ERROR)
        raise SystemExit(1)
    return {str(key): value for key, value in parsed.items()}


def _select_subject_paths(
    raw: Mapping[str, object], kind: str, paths: list[str]
) -> dict[str, object]:  # guard: loose-dict - heterogeneous rendered config view
    """Resolve document-relative paths before compatible envelope-prefixed paths."""
    document = raw.get(kind)
    if not isinstance(document, Mapping):
        return _select_paths(raw, paths)
    selected: dict[str, object] = {}  # guard: loose-dict - heterogeneous rendered config view
    legacy_paths: list[str] = []
    for path in paths:
        try:
            subtree = _extract_subtree(document, path)
        except KeyError:
            legacy_paths.append(path)
        else:
            _merge(selected, {kind: subtree})
    _merge(selected, _select_paths(raw, legacy_paths))
    return selected


def _select_paths(
    raw: Mapping[str, object], paths: list[str]
) -> dict[str, object]:  # guard: loose-dict - heterogeneous rendered config view
    """Select declared subtrees from one rendered view."""
    selected: dict[str, object] = {}  # guard: loose-dict - heterogeneous rendered config view
    path_errors: list[str] = []
    for path in paths:
        try:
            _merge(selected, _extract_subtree(raw, path))
        except KeyError as error:
            path_errors.append(str(error))
    if path_errors:
        print(_ERRORS_HEADING)
        for path_error in path_errors:
            print(_ERROR_ROW.format(error=path_error))
        raise SystemExit(1)
    return selected


def _extract_subtree(
    raw: Mapping[str, object], path: str
) -> dict[str, object]:  # guard: loose-dict - heterogeneous rendered config view
    """Extract one dotted path without exposing raw-document mutation."""
    result: dict[str, object] = {}  # guard: loose-dict - heterogeneous rendered config view
    target = result
    source: object = raw
    parts = path.split(".")
    for index, part in enumerate(parts):
        if not isinstance(source, Mapping) or part not in source:
            raise KeyError(_PATH_NOT_FOUND_ERROR.format(path=path, segment=part))
        node = source[part]
        if index == len(parts) - 1:
            target[part] = node
            continue
        child: dict[str, object] = {}  # guard: loose-dict - heterogeneous rendered config view
        target[part] = child
        target = child
        source: object = node
    return result


def _merge(
    base: dict[str, object],  # guard: loose-dict - heterogeneous rendered config view
    addition: Mapping[str, object],
) -> None:
    """Merge selected subtrees into the command output only."""
    for key, value in addition.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge(current, value)
        else:
            base[key] = value


def _render(data: Mapping[str, object], output_format: str) -> None:
    """Render one config-owned result at the CLI edge."""
    if output_format == _JSON:
        print(json.dumps(data, indent=2, default=_json_default))
        return
    print(yaml.dump(_to_plain(data), sort_keys=False).strip())


def _json_default(value: object) -> object:
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _to_plain(data: object) -> object:
    """Recursively convert dataclasses/mappings into plain YAML-safe structures."""
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        return {field.name: _to_plain(getattr(data, field.name)) for field in dataclasses.fields(data)}
    if isinstance(data, Mapping):
        return {key: _to_plain(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_to_plain(item) for item in data]
    return data
