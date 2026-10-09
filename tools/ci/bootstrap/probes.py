"""Exercise configuration authorization and identity in the disposable VM."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from teleclaude.config.identity_schema import CompanyRole

if TYPE_CHECKING:
    from .__main__ import BootstrapHarness, GuestTerminal

_UTF8 = "utf-8"
_EMPTY_VALUE = ""
_ANSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SEED_DIRECTORY = "seed"
_PEOPLE_SEED_FILENAME = "people.yaml"
_COMPANY_KEY = "company"
_PEOPLE_KEY = "people"
_NAME_KEY = "name"
_SLUG_KEY = "slug"
_EMAIL_KEY = "email"
_MEMBERS_KEY = "members"
_ROLE_KEY = "role"
_PROJECTS_KEY = "projects"
_PROJECT_SECTION = "project"
_PERSON_SECTION = "identity"
_COMPANY_FIELD = "company"
_REVISION_FIELD = "revision"
_JSON_FORMAT = "json"
_JSON_OBJECT_START = "{"
GUEST_TELEC_RELATIVE_PATH = Path(".local") / "bin" / "telec"
_ROLE_CUSTOMER_REFUSAL_FRAGMENT = "role 'customer'"
_LOGIN_REQUIRED_REFUSAL_FRAGMENT = "login required"
_REFUSAL_EXIT_CODE = 1
_SEED_COMPANY_INVALID = "Probe people seed has an invalid company declaration."
_SEED_PEOPLE_INVALID = "Probe people seed has an invalid people list."
_SEED_PERSON_INVALID = "Probe people seed contains an invalid person entry."
_SEED_PERSON_MISSING = "Probe people seed does not declare the person {slug}."
_REVISION_MISSING = "The configuration view did not render a non-empty revision."
_SECTION_MISSING = "The configuration view did not render a {section} section."
_PROJECT_OWNERSHIP_MISSING = "Project {slug} does not render company {company}; its owner declaration did not land."
_CONFIG_PERSON_INIT = ("config", "person", "init")
_CONFIG_COMPANY_INIT = ("config", "company", "init")
_CONFIG_PROJECT_ADOPT = ("config", "project", "adopt")
_CONFIG_PERSON_GET = ("config", "person", "get")
_CONFIG_PERSON_PATCH = ("config", "person", "patch")
_CONFIG_COMPANY_GET = ("config", "company", "get")
_CONFIG_COMPANY_PATCH = ("config", "company", "patch")
_CONFIG_PROJECT_GET = ("config", "project", "get")
_CONFIG_PROJECT_PATCH = ("config", "project", "patch")
_CONFIG_GLOBAL_GET = ("config", "global", "get")
_CONFIG_GLOBAL_PATCH = ("config", "global", "patch")
_CONFIG_FORMAT_FLAG = "--format"
_CONFIG_EMAIL_FLAG = "--email"
_CONFIG_SLUG_FLAG = "--slug"
_CONFIG_REVISION_FLAG = "--revision"
_CONFIG_YAML_FLAG = "--yaml"
_CONFIG_REMOVE_FLAG = "--remove"
_AUTH_LOGIN = ("auth", "login")
_CHANGE_DIRECTORY_COMMAND = "cd"
_PROJECTS_DIRECTORY = "bootstrap-probe-projects"
_PROJECT_SLUGS = ("proj-a", "proj-b")
_MKDIR_BINARY = "/bin/mkdir"
_MKDIR_PARENTS_OPTION = "-p"
_GIT_BINARY = "git"
_GIT_CHANGE_DIRECTORY_OPTION = "-C"
_GIT_INIT_COMMAND = "init"
_COMPANY_ADMIN_SLUG = "coadmin"
_PROJECT_MEMBER_SLUG = "member1"
_CUSTOMER_SLUG = "cust1"
_REMOVED_PERSON_SLUG = "gone1"
_UNKNOWN_PERSON_EMAIL = "unknown@probe.invalid"
_MINIMAL_GLOBAL_PATCH = "global: {}"
_GLOBAL_CONFIG_KIND = "global"
_PERSON_KIND = "person"
_COMPANY_KIND = "company"
_PROJECT_KIND = "project"
_VENV_PYTHON = Path(".venv") / "bin" / "python"
_PYTHON_MODULE_OPTION = "-m"
_MACOS_SETUP_MODULE = "teleclaude.entrypoints.macos_setup"
_PERMISSIONS_PROBE_ACTION = "permissions-probe"
_PROJECT_ROOT_OPTION = "--project-root"
_PERMISSIONS_COMMAND_TIMEOUT_SECONDS = 300
_FADA_PASSED_EXIT_CODE = 0
_FADA_DENIED_EXIT_CODE = 1
_LOGIN_ADMIN = "log in the seeded administrator for {purpose}"
_PURPOSE_FIXTURES = "fixture setup"
_PURPOSE_REMOVAL = "the removal probe"
_PURPOSE_FADA = "the permissions probe"
_PERSON_INITIALIZED = "register probe person {slug}"
_COMPANY_INITIALIZED = "initialize the probe company"
_COMPANY_ROSTER_PATCHED = "assign the company and project roles"
_PROJECT_CHECKOUT_CREATED = "create the probe repository directory {slug}"
_PROJECT_GIT_INITIALIZED = "initialize probe repository {slug}"
_PROJECT_DIRECTORY_SELECTED = "select probe project directory {slug}"
_PROJECT_ADOPTED = "register the probe project {slug}"
_PROJECT_COMPANY_PATCHED = "assign project {slug} to the probe company"
_RETURN_TO_CHECKOUT = "return to the TeleClaude checkout"
_READ_REVISION = "read {kind} {slug} revision before patch"
_PROJECT_VIEW_READ = "read project {slug} as the administrator"
_PROJECT_OWNED = "project {slug} renders the probe company as its owner"
_PERSON_LOGIN = "log in {slug} on its own terminal"
_PERSON_ACTION_ALLOWED = "{slug} performs its allowed action"
_PERSON_ACTION_RENDERED = "{slug}'s allowed action renders its configuration and revision"
_PERSON_ACTION_REFUSED = "{slug} is refused its unauthorized action"
_PERSON_REMOVED = "remove the probe person with its current revision"
_UNKNOWN_LOGIN = "log in the unknown probe identity"
_UNKNOWN_REFUSED = "an unknown identity is refused config access"
_REMOVED_LOGIN = "log in the removed probe identity"
_REMOVED_REFUSED = "a removed identity is refused config access"
_FADA_COMMAND = "Full Disk Access capability"
_FADA_AVAILABLE = "available"
_FADA_DENIED = "not available"
_FADA_NO_RESULT = "no result (exit {exit_code})"
_GUEST_GLOBAL_PLACEHOLDER = "-"


class ProbeFailure(RuntimeError):
    """A probe fixture or rendered view did not match what the probe requires."""


@dataclass(frozen=True)
class ProbePerson:
    """One person fixture used by the role and identity probes."""

    slug: str
    name: str
    email: str


@dataclass(frozen=True)
class ProbeFixtures:
    """Validated company and people fixtures loaded from the repository seed."""

    company_name: str
    company_slug: str
    people: tuple[ProbePerson, ...]

    def person(self, slug: str) -> ProbePerson:
        """Return the fixture person with this slug."""
        for person in self.people:
            if person.slug == slug:
                return person
        raise ProbeFailure(_SEED_PERSON_MISSING.format(slug=slug))


@dataclass(frozen=True)
class RenderedView:
    """One rendered configuration view: its sections and its non-empty revision."""

    fields: Mapping[str, object]
    revision: str


def _mapping_value(raw: object) -> Mapping[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    return {str(key): value for key, value in raw.items()}


def _load_fixtures() -> ProbeFixtures:
    seed_path = Path(__file__).resolve().parent / _SEED_DIRECTORY / _PEOPLE_SEED_FILENAME
    try:
        loaded: object = yaml.safe_load(seed_path.read_text(encoding=_UTF8))
    except (OSError, yaml.YAMLError) as exc:
        raise ProbeFailure(_SEED_PEOPLE_INVALID) from exc
    root = _mapping_value(loaded)
    if root is None:
        raise ProbeFailure(_SEED_PEOPLE_INVALID)
    company = _mapping_value(root.get(_COMPANY_KEY))
    if company is None:
        raise ProbeFailure(_SEED_COMPANY_INVALID)
    company_name = company.get(_NAME_KEY)
    company_slug = company.get(_SLUG_KEY)
    if not isinstance(company_name, str) or not isinstance(company_slug, str):
        raise ProbeFailure(_SEED_COMPANY_INVALID)
    raw_people = root.get(_PEOPLE_KEY)
    if not isinstance(raw_people, list):
        raise ProbeFailure(_SEED_PEOPLE_INVALID)
    people: list[ProbePerson] = []
    for raw_person in raw_people:
        person = _mapping_value(raw_person)
        if person is None:
            raise ProbeFailure(_SEED_PERSON_INVALID)
        slug = person.get(_SLUG_KEY)
        name = person.get(_NAME_KEY)
        email = person.get(_EMAIL_KEY)
        if not isinstance(slug, str) or not isinstance(name, str) or not isinstance(email, str):
            raise ProbeFailure(_SEED_PERSON_INVALID)
        if not slug.strip() or not name.strip() or not email.strip():
            raise ProbeFailure(_SEED_PERSON_INVALID)
        people.append(ProbePerson(slug=slug, name=name, email=email))
    return ProbeFixtures(company_name=company_name, company_slug=company_slug, people=tuple(people))


def _telec_path(harness: BootstrapHarness) -> str:
    return str(Path(harness.guest_home) / GUEST_TELEC_RELATIVE_PATH)


def _rendered_view(output: str) -> RenderedView | None:
    """Find the rendered configuration view in a terminal capture, or None when it is absent."""
    plain = _ANSI_SEQUENCE.sub(_EMPTY_VALUE, output)
    decoder = json.JSONDecoder()
    for index, character in enumerate(plain):
        if character != _JSON_OBJECT_START:
            continue
        try:
            value, _ = decoder.raw_decode(plain[index:])
        except json.JSONDecodeError:
            continue
        fields = _mapping_value(value)
        revision = fields.get(_REVISION_FIELD) if fields is not None else None
        if fields is not None and isinstance(revision, str) and revision:
            return RenderedView(fields=fields, revision=revision)
    return None


def _view_defect(output: str, section: str) -> str | None:
    """Name why a capture does not hold a rendered view of this section, or None when it does."""
    view = _rendered_view(output)
    if view is None:
        return _REVISION_MISSING
    if _mapping_value(view.fields.get(section)) is None:
        return _SECTION_MISSING.format(section=section)
    return None


def _read_revision(
    harness: BootstrapHarness,
    terminal: GuestTerminal,
    telec: str,
    kind: str,
    slug: str | None,
) -> str:
    resource_get = {
        _PERSON_KIND: _CONFIG_PERSON_GET,
        _COMPANY_KIND: _CONFIG_COMPANY_GET,
        _PROJECT_KIND: _CONFIG_PROJECT_GET,
        _GLOBAL_CONFIG_KIND: _CONFIG_GLOBAL_GET,
    }[kind]
    command = [telec, *resource_get]
    if slug is not None:
        command.append(slug)
    command.extend((_CONFIG_FORMAT_FLAG, _JSON_FORMAT))
    result = terminal.run(command)
    harness.record_terminal_result(_READ_REVISION.format(kind=kind, slug=slug or _GUEST_GLOBAL_PLACEHOLDER), result)
    view = _rendered_view(result.output)
    if view is None:
        raise ProbeFailure(_REVISION_MISSING)
    return view.revision


def _require_project_ownership(
    harness: BootstrapHarness,
    terminal: GuestTerminal,
    telec: str,
    project_slug: str,
    company_slug: str,
) -> None:
    """Read a project as the administrator and require its rendered owner to be the fixture company."""
    result = terminal.run([telec, *_CONFIG_PROJECT_GET, project_slug, _CONFIG_FORMAT_FLAG, _JSON_FORMAT])
    harness.record_terminal_result(_PROJECT_VIEW_READ.format(slug=project_slug), result)
    view = _rendered_view(result.output)
    project = _mapping_value(view.fields.get(_PROJECT_SECTION)) if view is not None else None
    owned = project is not None and project.get(_COMPANY_FIELD) == company_slug
    harness.record_probe(
        _PROJECT_OWNED.format(slug=project_slug),
        owned,
        _PROJECT_OWNERSHIP_MISSING.format(slug=project_slug, company=company_slug),
    )


def _register_project(
    harness: BootstrapHarness,
    terminal: GuestTerminal,
    telec: str,
    project_slug: str,
    company_slug: str,
) -> None:
    project_root = str(Path(harness.guest_home) / _PROJECTS_DIRECTORY / project_slug)
    harness.run_vm_command(
        _PROJECT_CHECKOUT_CREATED.format(slug=project_slug),
        [_MKDIR_BINARY, _MKDIR_PARENTS_OPTION, project_root],
    )
    harness.run_vm_command(
        _PROJECT_GIT_INITIALIZED.format(slug=project_slug),
        [_GIT_BINARY, _GIT_CHANGE_DIRECTORY_OPTION, project_root, _GIT_INIT_COMMAND],
    )
    selected = terminal.run([_CHANGE_DIRECTORY_COMMAND, project_root])
    harness.record_terminal_result(_PROJECT_DIRECTORY_SELECTED.format(slug=project_slug), selected)
    adopted = terminal.run([telec, *_CONFIG_PROJECT_ADOPT])
    harness.record_terminal_result(_PROJECT_ADOPTED.format(slug=project_slug), adopted)
    revision = _read_revision(harness, terminal, telec, _PROJECT_KIND, project_slug)
    patch = yaml.safe_dump({_COMPANY_FIELD: company_slug}, sort_keys=False)
    patched = terminal.run(
        [telec, *_CONFIG_PROJECT_PATCH, project_slug, _CONFIG_REVISION_FLAG, revision, _CONFIG_YAML_FLAG, patch]
    )
    harness.record_terminal_result(_PROJECT_COMPANY_PATCHED.format(slug=project_slug), patched)


def _run_admin_fixtures(harness: BootstrapHarness, fixtures: ProbeFixtures, owner_email: str) -> str:
    """Create the probe people, company and projects as the seeded administrator; return the global revision."""
    telec = _telec_path(harness)
    with harness.terminal() as terminal:
        login = terminal.run([telec, *_AUTH_LOGIN, owner_email])
        harness.record_terminal_result(_LOGIN_ADMIN.format(purpose=_PURPOSE_FIXTURES), login)
        for person in fixtures.people:
            initialized = terminal.run(
                [
                    telec,
                    *_CONFIG_PERSON_INIT,
                    person.name,
                    _CONFIG_EMAIL_FLAG,
                    person.email,
                ]
            )
            harness.record_terminal_result(_PERSON_INITIALIZED.format(slug=person.slug), initialized)

        company_initialized = terminal.run(
            [telec, *_CONFIG_COMPANY_INIT, fixtures.company_name, _CONFIG_SLUG_FLAG, fixtures.company_slug]
        )
        harness.record_terminal_result(_COMPANY_INITIALIZED, company_initialized)

        for project_slug in _PROJECT_SLUGS:
            _register_project(harness, terminal, telec, project_slug, fixtures.company_slug)
        returned = terminal.run([_CHANGE_DIRECTORY_COMMAND, harness.guest_project_root])
        harness.record_terminal_result(_RETURN_TO_CHECKOUT, returned)

        company_revision = _read_revision(harness, terminal, telec, _COMPANY_KIND, fixtures.company_slug)
        company_patch = yaml.safe_dump(
            {
                _MEMBERS_KEY: {
                    fixtures.person(_COMPANY_ADMIN_SLUG).slug: {_ROLE_KEY: CompanyRole.ADMIN.value},
                    fixtures.person(_PROJECT_MEMBER_SLUG).slug: {
                        _ROLE_KEY: CompanyRole.MEMBER.value,
                        _PROJECTS_KEY: [_PROJECT_SLUGS[0]],
                    },
                }
            },
            sort_keys=False,
        )
        roster_patched = terminal.run(
            [
                telec,
                *_CONFIG_COMPANY_PATCH,
                fixtures.company_slug,
                _CONFIG_REVISION_FLAG,
                company_revision,
                _CONFIG_YAML_FLAG,
                company_patch,
            ]
        )
        harness.record_terminal_result(_COMPANY_ROSTER_PATCHED, roster_patched)

        for project_slug in _PROJECT_SLUGS:
            _require_project_ownership(harness, terminal, telec, project_slug, fixtures.company_slug)
        return _read_revision(harness, terminal, telec, _GLOBAL_CONFIG_KIND, None)


def _run_person_actions(
    harness: BootstrapHarness,
    telec: str,
    person: ProbePerson,
    allowed_command: Sequence[str],
    refused_command: Sequence[str],
    *,
    rendered_section: str | None = None,
) -> None:
    """Log one person in on a terminal of their own, then run an allowed and a refused command."""
    with harness.terminal() as terminal:
        login = terminal.run([telec, *_AUTH_LOGIN, person.email])
        harness.record_terminal_result(_PERSON_LOGIN.format(slug=person.slug), login)
        allowed = terminal.run(allowed_command)
        harness.record_terminal_result(_PERSON_ACTION_ALLOWED.format(slug=person.slug), allowed)
        if rendered_section is not None:
            defect = _view_defect(allowed.output, rendered_section)
            harness.record_probe(
                _PERSON_ACTION_RENDERED.format(slug=person.slug),
                defect is None,
                defect or _EMPTY_VALUE,
            )
        refused = terminal.run(refused_command)
        harness.record_terminal_result(
            _PERSON_ACTION_REFUSED.format(slug=person.slug),
            refused,
            expected_returncode=_REFUSAL_EXIT_CODE,
            expected_text=_ROLE_CUSTOMER_REFUSAL_FRAGMENT,
        )


def _run_unrecognized_identity_probe(
    harness: BootstrapHarness,
    telec: str,
    email: str,
    login_name: str,
    refusal_name: str,
) -> None:
    """Log in an email the registry does not resolve, then require a gated command to name the missing login."""
    with harness.terminal() as terminal:
        login = terminal.run([telec, *_AUTH_LOGIN, email])
        harness.record_terminal_result(login_name, login)
        refused = terminal.run([telec, *_CONFIG_PERSON_GET, _CUSTOMER_SLUG])
        harness.record_terminal_result(
            refusal_name,
            refused,
            expected_returncode=_REFUSAL_EXIT_CODE,
            expected_text=_LOGIN_REQUIRED_REFUSAL_FRAGMENT,
        )


def _remove_person(harness: BootstrapHarness, telec: str, person: ProbePerson, owner_email: str) -> None:
    """Remove a person with the revision read immediately before, as the seeded administrator."""
    with harness.terminal() as terminal:
        login = terminal.run([telec, *_AUTH_LOGIN, owner_email])
        harness.record_terminal_result(_LOGIN_ADMIN.format(purpose=_PURPOSE_REMOVAL), login)
        revision = _read_revision(harness, terminal, telec, _PERSON_KIND, person.slug)
        removal = terminal.run(
            [telec, *_CONFIG_PERSON_PATCH, person.slug, _CONFIG_REVISION_FLAG, revision, _CONFIG_REMOVE_FLAG]
        )
        harness.record_terminal_result(_PERSON_REMOVED, removal)


def _report_full_disk_access(harness: BootstrapHarness, owner_email: str, telec: str) -> None:
    """Report the existing permissions probe as a capability line, outside the health verdict."""
    python = str(Path(harness.guest_project_root) / _VENV_PYTHON)
    with harness.terminal(_PERMISSIONS_COMMAND_TIMEOUT_SECONDS) as terminal:
        login = terminal.run([telec, *_AUTH_LOGIN, owner_email])
        harness.record_terminal_result(_LOGIN_ADMIN.format(purpose=_PURPOSE_FADA), login)
        result = terminal.run(
            [
                python,
                _PYTHON_MODULE_OPTION,
                _MACOS_SETUP_MODULE,
                _PERMISSIONS_PROBE_ACTION,
                _PROJECT_ROOT_OPTION,
                harness.guest_project_root,
            ]
        )
    if result.returncode == _FADA_PASSED_EXIT_CODE:
        status = _FADA_AVAILABLE
    elif result.returncode == _FADA_DENIED_EXIT_CODE:
        status = _FADA_DENIED
    else:
        status = _FADA_NO_RESULT.format(exit_code=result.returncode)
    harness.record_information(_FADA_COMMAND, status)


def run_role_and_identity_probes(harness: BootstrapHarness, owner_email: str) -> None:
    """Run the allowed/refused configuration pairs and report Full Disk Access separately."""
    fixtures = _load_fixtures()
    telec = _telec_path(harness)
    global_revision = _run_admin_fixtures(harness, fixtures, owner_email)

    _run_person_actions(
        harness,
        telec,
        fixtures.person(_COMPANY_ADMIN_SLUG),
        [telec, *_CONFIG_COMPANY_GET, fixtures.company_slug],
        [
            telec,
            *_CONFIG_GLOBAL_PATCH,
            _CONFIG_REVISION_FLAG,
            global_revision,
            _CONFIG_YAML_FLAG,
            _MINIMAL_GLOBAL_PATCH,
        ],
    )
    _run_person_actions(
        harness,
        telec,
        fixtures.person(_PROJECT_MEMBER_SLUG),
        [telec, *_CONFIG_PROJECT_GET, _PROJECT_SLUGS[0]],
        [telec, *_CONFIG_PROJECT_GET, _PROJECT_SLUGS[1]],
    )
    customer = fixtures.person(_CUSTOMER_SLUG)
    _run_person_actions(
        harness,
        telec,
        customer,
        [telec, *_CONFIG_PERSON_GET, customer.slug, _CONFIG_FORMAT_FLAG, _JSON_FORMAT],
        [telec, *_CONFIG_PROJECT_GET, _PROJECT_SLUGS[0]],
        rendered_section=_PERSON_SECTION,
    )
    _run_unrecognized_identity_probe(harness, telec, _UNKNOWN_PERSON_EMAIL, _UNKNOWN_LOGIN, _UNKNOWN_REFUSED)
    removed = fixtures.person(_REMOVED_PERSON_SLUG)
    _remove_person(harness, telec, removed, owner_email)
    _run_unrecognized_identity_probe(harness, telec, removed.email, _REMOVED_LOGIN, _REMOVED_REFUSED)
    _report_full_disk_access(harness, owner_email, telec)
