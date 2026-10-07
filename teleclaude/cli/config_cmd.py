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
from typing import Any

import yaml
from redis.exceptions import RedisError

from teleclaude.cli.session_auth import ResolvedCliIdentity, resolve_cli_identity
from teleclaude.cli.telec import flags as F
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
    CONFIG_PROJECT_GET,
    CONFIG_PROJECT_HELP_DESK_LINKS,
    CONFIG_PROJECT_INIT,
    CONFIG_PROJECT_LIST,
    CONFIG_PROJECT_PATCH,
)
from teleclaude.config import config
from teleclaude.config.person_voice import configure_person_discord_voice_bot
from teleclaude.config.project_subject_init import init_project_subject
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
from teleclaude.config.roster import RosterOutcome, RosterRefused
from teleclaude.config.surface import machine_config_surface
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.configuration_clearance import (
    HELP_DESK_SECTION,
    ConfigurationOperation,
    ConfigurationTarget,
    decide,
    is_administrator,
    standing_for,
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
from teleclaude.docs_index import get_project_slug
from teleclaude.invite import invite_person, render_help_desk_links
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.slug import normalize_slug

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
_PROJECT_INIT_COMPLETE = "telec config project init complete."
_SLUG_FIELD = "slug"
_REDACTED_VALUE = "<redacted: platform administrator required>"
_HELP_DESK_LINKS_VERB = "help-desk-links"
_DESK_NOT_ENABLED_ERROR = "Error: help desk of {kind} {slug} is not enabled{request}"
_DESK_NOT_HOSTED_ERROR = "Error: this computer does not host the help desk of {kind} {slug}{request}"
_FLEET_UNOBSERVABLE_ERROR = "Error: cannot observe the fleet: {error}{request}"
# The keys of the help-desk links JSON answer.
_LINKS_IDENTIFIER_KEY = "identifier"
_LINKS_KEY = "links"
_LINKS_REQUEST_ID_KEY = "request_id"
_FLEET_LAGGING_ERROR = (
    "Error: help-desk entry is not served until every computer runs it; lagging: {computers}{request}"
)
_NO_LINKS_LINE = "No entry links could be generated for {identifier}."
_LINK_LINE = "  {adapter}: {link}"
_DISCORD_LINK_LINE = "  {adapter}: {link} (send {identifier} as your first message)"
_LINKS_HEADING = "Entry links for {identifier}:"
_DISCORD_ADAPTER = "discord"
_LIST_SEPARATOR = ", "

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
    "project": CONFIG_PROJECT_INIT,
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
        print(f"Usage: telec config {kind} <list|get|init|patch>")
        raise SystemExit(1)
    verb, verb_args = args[0], args[1:]
    request_id = str(uuid.uuid4())

    if verb == "list":
        _handle_list(kind, subject_kind, verb_args, request_id)
    elif verb == "get":
        _handle_get(kind, subject_kind, verb_args, request_id)
    elif verb == "init":
        _handle_init(kind, subject_kind, verb_args, request_id)
    elif verb == "patch":
        _handle_patch(kind, subject_kind, verb_args, request_id)
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
) -> ResolvedCliIdentity:
    """Verb band, then target clearance. Refuses and exits before any config is read."""
    identity = resolve_cli_identity()
    standing = standing_for(identity)
    target = ConfigurationTarget(kind=subject_kind, instance=instance, operation=operation, sections=sections)
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


# --- list ---


def _handle_list(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parse_command_args(_LIST_COMMAND_DEFS[kind], args)
    _gate(
        kind,
        "list",
        subject_kind,
        instance=None,
        operation=ConfigurationOperation.LIST,
        sections=frozenset(),
        request_id=request_id,
    )
    refs = list_subjects(subject_kind)
    if not refs:
        print(f"No {kind} subjects.")
        return
    for ref in refs:
        print(ref.instance if ref.instance is not None else f"({kind})")


# --- get ---


def _redact_path(document: dict[str, object], path: tuple[str, ...]) -> None:  # guard: loose-dict - raw YAML config
    """Replace one schema-declared sensitive leaf in place, if the path is present."""
    node: object = document
    for part in path[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict) and path[-1] in node:
        node[path[-1]] = _REDACTED_VALUE


def _redact_sensitive_machine_fields(
    computer_section: Mapping[str, object],
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Redact every schema-declared sensitive machine leaf for a non-administrator caller."""
    redacted = _to_plain(computer_section)
    if not isinstance(redacted, dict):
        return dict(computer_section)
    for descriptor in machine_config_surface():
        if descriptor.sensitive:
            _redact_path(redacted, descriptor.path)
    return redacted


def _handle_get(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_GET_COMMAND_DEFS[kind], args)
    instance, paths = _require_instance(kind, subject_kind, parsed.positionals)
    output_format = _output_format(parsed.value(F.FLAG_CONFIG_FORMAT))
    identity = _gate(
        kind,
        "get",
        subject_kind,
        instance=instance,
        operation=ConfigurationOperation.GET,
        sections=frozenset(),
        request_id=request_id,
    )
    try:
        view = read_subject(SubjectRef(subject_kind, instance))
    except SubjectNotFound as error:
        print(_NOT_FOUND_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    read_only = dict(view.read_only)
    if subject_kind is ConfigSubjectKind.PERSON and instance is not None:
        read_only["roles"] = person_roles(instance)
    sections = dict(view.sections)
    if subject_kind is ConfigSubjectKind.COMPUTER and not is_administrator(standing_for(identity)):
        computer_section = sections.get(kind)
        if isinstance(computer_section, Mapping):
            sections[kind] = _redact_sensitive_machine_fields(computer_section)
    merged: dict[str, object] = {**sections, **read_only}  # guard: loose-dict - heterogeneous rendered config view
    rendered = _select_paths(merged, list(paths)) if paths else merged
    _render({**rendered, "revision": view.revision, "request_id": request_id}, output_format)


# --- init ---


def _run_init(
    compute: Callable[[], SubjectView],
    output_format: str,
    request_id: str,
    *,
    completion_line: str | None = None,
) -> None:
    """Run one init call, rendering its view or a clean error for every typed refusal."""
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


def _handle_init(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_INIT_COMMAND_DEFS[kind], args)
    output_format = _output_format(None)
    help_desk = F.FLAG_HELP_DESK in _INIT_COMMAND_DEFS[kind].flags and parsed.has(F.FLAG_HELP_DESK)
    sections = frozenset({HELP_DESK_SECTION}) if help_desk else frozenset()

    if subject_kind is ConfigSubjectKind.PROJECT:
        adoption_root = resolve_invocation_roots().adoption_root()
        _gate(
            kind,
            "init",
            subject_kind,
            instance=get_project_slug(adoption_root) if help_desk else None,
            operation=ConfigurationOperation.INIT,
            sections=sections,
            request_id=request_id,
        )
        _run_init(
            lambda: init_project_subject(adoption_root, request_id=request_id, help_desk=help_desk),
            output_format,
            request_id,
            completion_line=_PROJECT_INIT_COMPLETE,
        )
        return

    if subject_kind in _SINGLETON_KINDS:
        _gate(
            kind,
            "init",
            subject_kind,
            instance=None,
            operation=ConfigurationOperation.INIT,
            sections=sections,
            request_id=request_id,
        )
        singleton_fields = {HELP_DESK_SECTION: True} if help_desk else None
        _run_init(
            lambda: init_subject(SubjectRef(subject_kind, None), singleton_fields, request_id=request_id),
            output_format,
            request_id,
        )
        return

    # person / company: fields come from init flags, not from an instance the
    # caller has not yet named (a brand-new person/company has no slug until
    # the engine derives or the caller supplies one).
    if not parsed.positionals:
        print(f"Error: {kind} init requires a name.")
        raise SystemExit(1)
    name = parsed.positionals[0]
    company_slug = parsed.value(F.FLAG_COMPANY_SLUG) if subject_kind is ConfigSubjectKind.COMPANY else None
    _gate(
        kind,
        "init",
        subject_kind,
        instance=(company_slug or normalize_slug(name)) if help_desk else None,
        operation=ConfigurationOperation.INIT,
        sections=sections,
        request_id=request_id,
    )
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
        if help_desk:
            fields[HELP_DESK_SECTION] = True
    _run_init(
        lambda: init_subject(SubjectRef(subject_kind, None), fields, request_id=request_id),
        output_format,
        request_id,
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
        _gate(
            kind,
            "patch",
            subject_kind,
            instance=instance,
            operation=ConfigurationOperation.REMOVE,
            sections=frozenset(),
            request_id=request_id,
        )
        assert instance is not None
        delete_dir = parsed.has(F.FLAG_PEOPLE_DELETE_DIR)
        try:
            outcome = remove_person_subject(
                SubjectRef(subject_kind, instance), delete_dir=delete_dir, request_id=request_id
            )
        except PartialCommitFailure as error:
            print(
                _PARTIAL_COMMIT_MESSAGE.format(
                    message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)
                )
            )
            raise SystemExit(1) from error
        except SubjectNotFound as error:
            print(_NOT_FOUND_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
            raise SystemExit(1) from error
        _render(_roster_outcome_payload(outcome, request_id), output_format)
        return

    patch = _read_patch(parsed.value(F.FLAG_CONFIG_FROM_FILE), parsed.value(F.FLAG_CONFIG_YAML))
    ref = SubjectRef(subject_kind, instance)
    sections = affected_sections(ref, patch)
    _gate(
        kind,
        "patch",
        subject_kind,
        instance=instance,
        operation=ConfigurationOperation.PATCH,
        sections=sections,
        request_id=request_id,
    )
    try:
        view = patch_subject(ref, patch, expected_revision=revision, request_id=request_id)
    except StaleRevision as error:
        print(
            _STALE_MESSAGE.format(
                expected=error.expected, actual=error.actual, request=_REQUEST_SUFFIX.format(request_id=request_id)
            )
        )
        raise SystemExit(1) from error
    except PartialCommitFailure as error:
        print(_PARTIAL_COMMIT_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    except (InvalidCandidate, ReadOnlyProjection, RosterRefused) as error:
        print(_INVALID_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    except SubjectNotFound as error:
        print(_NOT_FOUND_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    _render({**view.sections, "revision": view.revision, "request_id": request_id}, output_format)


def _roster_outcome_payload(
    outcome: RosterOutcome, request_id: str
) -> dict[str, object]:  # guard: loose-dict - rendered CLI payload, not a config document
    return {
        "companies_written": list(outcome.companies_written),
        "removed_assignments": [list(pair) for pair in outcome.removed_assignments],
        "request_id": request_id,
    }


# --- person invite / discord-voice-bot ---


def _handle_invite(args: list[str], request_id: str) -> None:
    parsed = parse_command_args(CONFIG_PERSON_INVITE, args)
    if not parsed.positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind="person"))
        raise SystemExit(1)
    slug = parsed.positionals[0]
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    _gate(
        "person",
        "invite",
        ConfigSubjectKind.PERSON,
        instance=slug,
        operation=ConfigurationOperation.INVITE,
        sections=frozenset(),
        request_id=request_id,
    )
    try:
        outcome = invite_person(slug)
    except ValueError as error:
        print(_INVALID_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    payload = {
        "name": outcome.name,
        "email": outcome.email,
        "links": outcome.links,
        "email_sent": outcome.email_sent,
        "request_id": request_id,
    }
    if use_json:
        print(json.dumps(payload))
        return
    if outcome.email_sent:
        print(f"Invite sent to {outcome.email} for {outcome.name}{_REQUEST_SUFFIX.format(request_id=request_id)}")
    else:
        available = {platform: url for platform, url in outcome.links.items() if url}
        if available:
            relay = "\n".join(f"  {platform}: {url}" for platform, url in available.items())
            print(f"Invite for {outcome.name}: email not delivered — share these links directly:\n{relay}")
        else:
            print(f"Invite for {outcome.name}: email not delivered and no invite links could be generated.")


def _handle_discord_voice_bot(args: list[str], request_id: str) -> None:
    parsed = parse_command_args(CONFIG_PERSON_DISCORD_VOICE_BOT, args)
    if not parsed.positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind="person"))
        raise SystemExit(1)
    slug = parsed.positionals[0]
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    _gate(
        "person",
        "discord-voice-bot",
        ConfigSubjectKind.PERSON,
        instance=slug,
        operation=ConfigurationOperation.BIND_VOICE_BOT,
        sections=frozenset(),
        request_id=request_id,
    )
    try:
        result = configure_person_discord_voice_bot(slug, config.discord.token)
    except (OSError, ValueError) as error:
        print(_INVALID_MESSAGE.format(message=str(error), request=_REQUEST_SUFFIX.format(request_id=request_id)))
        raise SystemExit(1) from error
    fields = ["discord_voice_bot"]
    if result.environment_secured:
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
_DESK_KIND_BY_SUBJECT = {
    ConfigSubjectKind.COMPANY: HelpDeskKind.COMPANY,
    ConfigSubjectKind.PROJECT: HelpDeskKind.PROJECT,
}


def _handle_help_desk_links(kind: str, subject_kind: ConfigSubjectKind, args: list[str], request_id: str) -> None:
    parsed = parse_command_args(_HELP_DESK_LINKS_COMMAND_DEFS[subject_kind], args)
    if not parsed.positionals:
        print(_MISSING_INSTANCE_ERROR.format(kind=kind))
        raise SystemExit(1)
    slug = parsed.positionals[0]
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    _gate(
        kind,
        _HELP_DESK_LINKS_VERB,
        subject_kind,
        instance=slug,
        operation=ConfigurationOperation.HELP_DESK_LINKS,
        sections=frozenset(),
        request_id=request_id,
    )
    request = _REQUEST_SUFFIX.format(request_id=request_id)
    identifier = DeskIdentifier(_DESK_KIND_BY_SUBJECT[subject_kind], slug)
    if local_desk_endpoint(identifier, config.computer.name) is None:
        template = _DESK_NOT_ENABLED_ERROR if desk_home_present(identifier) else _DESK_NOT_HOSTED_ERROR
        print(template.format(kind=kind, slug=slug, request=request))
        raise SystemExit(1)
    try:
        fleet = asyncio.run(observe_fleet_from_heartbeats())
    except (OSError, RedisError) as error:
        print(_FLEET_UNOBSERVABLE_ERROR.format(error=error, request=request))
        raise SystemExit(1) from error
    if not fleet.conversation_entry_safe():
        computers = _LIST_SEPARATOR.join(fleet.lacking_conversation_entry())
        print(_FLEET_LAGGING_ERROR.format(computers=computers, request=request))
        raise SystemExit(1)
    rendered = identifier.render()
    links = asyncio.run(
        render_help_desk_links(rendered, telegram_allowed=len(rendered) <= TELEGRAM_START_PARAMETER_MAX)
    )
    if use_json:
        print(json.dumps({_LINKS_IDENTIFIER_KEY: rendered, _LINKS_KEY: links, _LINKS_REQUEST_ID_KEY: request_id}))
        return
    available = {adapter: link for adapter, link in links.items() if link}
    if not available:
        print(_NO_LINKS_LINE.format(identifier=rendered))
        return
    print(_LINKS_HEADING.format(identifier=rendered))
    for adapter, link in available.items():
        line = _DISCORD_LINK_LINE if adapter == _DISCORD_ADAPTER else _LINK_LINE
        print(line.format(adapter=adapter, link=link, identifier=rendered))


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
