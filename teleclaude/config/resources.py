"""Kind-addressed configuration resource engine.

Gives every configuration subject — computer, global, person, company, project
— the same verbs (list, read, init, patch) with one revisioned-optimistic-
concurrency contract. The addressing vocabulary, typed refusals, the
`config_resource_change` observation helper and the merge-patch and
multi-file commit primitives live in `teleclaude.config.resource_contract`;
subject enumeration lives in `teleclaude.config.resource_catalog`, and this
module owns every subject kind's read/init/patch implementation
(`sdlc/spec/feature/config/kind-addressed-configuration`).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import cast

import teleclaude.config as _tc_config_module
from teleclaude.company_setup.onboard_flow import scaffold_company
from teleclaude.config._environment import (
    expand_environment_references,
    find_environment_references,
    read_environment_file,
)
from teleclaude.config._file_io import file_transaction
from teleclaude.config.context_root import load_declared_config_kind
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.generation import ensure_machine_config
from teleclaude.config.loader import list_company_config_paths
from teleclaude.config.machine_config_mutation import (
    MachineConfigInspection,
    MachineConfigMutationResult,
    ReadOnlyDeclaration,
    inspect_machine_config,
    patch_machine_config_at,
)
from teleclaude.config.migrations import upcast
from teleclaude.config.migrations._runner import upcast_for_read
from teleclaude.config.person_registry import with_person, without_person
from teleclaude.config.resource_catalog import list_subjects as _list_subjects
from teleclaude.config.resource_catalog import load_mapping, raw_people
from teleclaude.config.resource_contract import (
    CommitEntry,
    InvalidCandidate,
    OwnEvidence,
    PartialCommitFailure,
    ReadOnlyProjection,
    ResourceChangeOutcome,
    ResourceOperation,
    SubjectNotFound,
    SubjectView,
    TargetDocument,
    apply_merge_patch,
    carry_resource_migrations,
    commit_documents,
    delivery_recorder,
    emit_resource_change,
    run_observed,
    target_id,
)
from teleclaude.config.revision import StaleRevision, view_revision
from teleclaude.config.roster import (
    RosterOutcome,
    rosters_without_person,
    validate_roster_candidate,
)
from teleclaude.config.schema import CompanyConfig, ConfigKind, GlobalConfig, PersonConfig, PersonEntry, ProjectConfig
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.docs_index import get_project_slug
from teleclaude.invite import scaffold_personal_workspace
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, PEOPLE_DIR, ConfigFileName
from teleclaude.project_setup.init_flow import ProjectInitializationResult, ProjectInitializationTrigger, init_project
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.slug import ensure_unique_slug, normalize_slug

_KIND_KEY = "kind"
_SCHEMA_VERSION_KEY = "schema_version"
_SLUG_KEY = "slug"
_NAME_KEY = "name"
_PEOPLE_KEY = "people"
_COMPUTER_SECTION = "computer"
_GLOBAL_SECTION = "global"
_IDENTITY_SECTION = "identity"
_SETTINGS_SECTION = "settings"
_ORGANIZATION_SECTION = "organization"
_COMPANY_SECTION = "company"
_PROJECT_SECTION = "project"
_PERSON_IDENTITY_FIELDS = frozenset({"name", "email", "username", "role", "preferences", "expertise"})
_DOCUMENT_MAPPING_ERROR = "Configuration document must be a mapping: {path}"
_READ_ONLY_SCHEMA_VERSION_ERROR = "`schema_version` is read-only; the migration list owns its value."

_SINGLETON_KINDS = frozenset({ConfigSubjectKind.COMPUTER, ConfigSubjectKind.GLOBAL})


def _upcast_mapping(
    document: Mapping[str, object], path: Path
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Build a current in-memory view from the path's registry or declaration subject."""
    return dict(upcast_for_read(path, document))


def _global_section(raw: Mapping[str, object]) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Project the global document's writable section, excluding people and read-only fields."""
    return {key: value for key, value in raw.items() if key not in (_PEOPLE_KEY, _KIND_KEY, _SCHEMA_VERSION_KEY)}


def list_subjects(kind: ConfigSubjectKind) -> list[SubjectRef]:
    """List every addressable subject of one kind."""
    return _list_subjects(kind)


def _global_revision(raw: Mapping[str, object]) -> str:
    return view_revision({_GLOBAL_SECTION: _global_section(raw)})


def _global_view(raw: Mapping[str, object]) -> SubjectView:
    return SubjectView(
        ref=SubjectRef(ConfigSubjectKind.GLOBAL),
        sources=(GLOBAL_CONFIG_PATH,),
        sections={_GLOBAL_SECTION: _global_section(raw)},
        read_only={},
        revision=_global_revision(raw),
    )


def _validate_global_candidate(candidate: Mapping[str, object]) -> None:  # guard: loose-dict - raw YAML config
    """Validate a full candidate global document (people included) as `GlobalConfig`."""
    references = find_environment_references(candidate)
    environment_path = GLOBAL_CONFIG_PATH.with_name(ConfigFileName.ENV)
    environment = read_environment_file(environment_path, owner_only=False) if references else {}
    expanded = expand_environment_references(candidate, environment, config_path=GLOBAL_CONFIG_PATH)
    if not isinstance(expanded, dict):
        raise InvalidCandidate(_DOCUMENT_MAPPING_ERROR.format(path=GLOBAL_CONFIG_PATH))
    try:
        # `kind` is a required discriminator field on the typed model but is never part of
        # the writable candidate — `render_declared_config` injects it at render time, the
        # same way every other overlay writer does. Supply it here for validation only.
        GlobalConfig.model_validate({**expanded, _KIND_KEY: ConfigKind.GLOBAL.value})
    except Exception as exc:
        raise InvalidCandidate(str(exc)) from exc


def _computer_source() -> Path:
    return _tc_config_module.config_path


def _computer_view_from(raw: Mapping[object, object], revision: str) -> SubjectView:
    sections: dict[str, object] = {  # guard: loose-dict - raw YAML config
        str(key): value for key, value in raw.items() if key not in {_KIND_KEY, _SCHEMA_VERSION_KEY}
    }
    return SubjectView(
        ref=SubjectRef(ConfigSubjectKind.COMPUTER),
        sources=(_computer_source(),),
        sections={_COMPUTER_SECTION: sections},
        read_only={},
        revision=revision,
    )


def _computer_view(inspection: MachineConfigInspection | MachineConfigMutationResult) -> SubjectView:
    return _computer_view_from(inspection.raw, inspection.revision)


# --- person helpers ---


def _person_overlay_path(slug: str) -> Path:
    return PEOPLE_DIR / slug / ConfigFileName.OVERLAY


def _person_init_lookup_key(fields: Mapping[str, object] | None) -> str | None:
    """Return the person key init will address, whether supplied or name-derived."""
    fields = fields or {}
    requested_slug = fields.get(_SLUG_KEY)
    if requested_slug:
        return str(requested_slug)
    name = fields.get(_NAME_KEY)
    return normalize_slug(str(name)) if name else None


def _person_is_registered(slug: str) -> bool:
    """Check the global registry without opening the person's overlay transaction."""
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        global_raw = load_mapping(transaction.read_text(), GLOBAL_CONFIG_PATH)
        return _find_person_raw(raw_people(global_raw), slug) is not None


def _find_person_raw(
    people: list[object], slug: str
) -> dict[str, object] | None:  # guard: loose-dict - raw YAML config
    """Locate one raw person entry by slug in a raw `people` list."""
    for entry in people:
        if isinstance(entry, dict) and entry.get(_SLUG_KEY) == slug:
            return cast(dict[str, object], entry)  # guard: loose-dict - raw YAML config
    return None


def _person_identity_section(
    entry_raw: Mapping[str, object],
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    return {key: value for key, value in entry_raw.items() if key != _SLUG_KEY}


def _person_settings_section(
    overlay_raw: Mapping[str, object],
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    return {key: value for key, value in overlay_raw.items() if key not in (_KIND_KEY, _SLUG_KEY, _SCHEMA_VERSION_KEY)}


def _person_revision(identity: Mapping[str, object], settings: Mapping[str, object]) -> str:
    return view_revision({_IDENTITY_SECTION: identity, _SETTINGS_SECTION: settings})


def _person_view(slug: str, global_raw: Mapping[str, object], overlay_raw: Mapping[str, object]) -> SubjectView:
    entry_raw = _find_person_raw(raw_people(global_raw), slug)
    if entry_raw is None:
        raise SubjectNotFound(f"person '{slug}' is not registered")
    identity = _person_identity_section(entry_raw)
    settings = _person_settings_section(overlay_raw)
    return SubjectView(
        ref=SubjectRef(ConfigSubjectKind.PERSON, slug),
        sources=(GLOBAL_CONFIG_PATH, _person_overlay_path(slug)),
        sections={_IDENTITY_SECTION: identity, _SETTINGS_SECTION: settings},
        read_only={},
        revision=_person_revision(identity, settings),
    )


def _split_person_patch(
    patch: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:  # guard: loose-dict - RFC 7386 patch source is caller-shaped
    """Split a flat person patch into its identity and settings sub-patches by field ownership.

    Identity and overlay top-level field names are disjoint (`PersonEntry` vs
    the person overlay), so a patch key belongs to whichever set names it;
    anything else falls to settings, which stays forward-compatible with new
    `PersonConfig` fields without this module tracking their names.
    """
    if _ORGANIZATION_SECTION in patch:
        raise ReadOnlyProjection("the `organization` section is a read-only projection, not writable here")
    if _SLUG_KEY in patch:
        raise InvalidCandidate("`slug` is immutable and cannot be patched")
    identity_patch = {key: value for key, value in patch.items() if key in _PERSON_IDENTITY_FIELDS}
    settings_patch = {key: value for key, value in patch.items() if key not in _PERSON_IDENTITY_FIELDS}
    return identity_patch, settings_patch


# --- company helpers ---


def _company_path(slug: str) -> Path:
    return COMPANIES_ROOT / slug / ConfigFileName.OVERLAY


def _company_section(raw: Mapping[str, object]) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    return {key: value for key, value in raw.items() if key not in (_KIND_KEY, _SLUG_KEY, _SCHEMA_VERSION_KEY)}


def _company_view(slug: str, raw: Mapping[str, object]) -> SubjectView:
    section = _company_section(raw)
    return SubjectView(
        ref=SubjectRef(ConfigSubjectKind.COMPANY, slug),
        sources=(_company_path(slug),),
        sections={_COMPANY_SECTION: section},
        read_only={},
        revision=view_revision({_COMPANY_SECTION: section}),
    )


# --- project helpers ---


def _project_root(slug: str) -> Path:
    node = get_project_catalog_service().get_by_slug(slug)
    if node is None:
        raise SubjectNotFound(f"project '{slug}' is not registered")
    return node.root


def _project_path(slug: str) -> Path:
    return _project_root(slug) / ConfigFileName.OVERLAY


def _project_section(raw: Mapping[str, object]) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    return {key: value for key, value in raw.items() if key not in (_KIND_KEY, _SCHEMA_VERSION_KEY)}


def _project_view(slug: str, raw: Mapping[str, object]) -> SubjectView:
    section = _project_section(raw)
    return SubjectView(
        ref=SubjectRef(ConfigSubjectKind.PROJECT, slug),
        sources=(_project_path(slug),),
        sections={_PROJECT_SECTION: section},
        read_only={},
        revision=view_revision({_PROJECT_SECTION: section}),
    )


# --- read_subject ---


def _read_computer(_ref: SubjectRef) -> SubjectView:
    return _computer_view(inspect_machine_config())


def _read_global(_ref: SubjectRef) -> SubjectView:
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        if not GLOBAL_CONFIG_PATH.exists():
            raise SubjectNotFound("global configuration has not been initialized")
        raw = _upcast_mapping(load_mapping(transaction.read_text(), GLOBAL_CONFIG_PATH), GLOBAL_CONFIG_PATH)
    return _global_view(raw)


def _read_person(ref: SubjectRef) -> SubjectView:
    assert ref.instance is not None
    slug = ref.instance
    with (
        file_transaction(GLOBAL_CONFIG_PATH) as g_txn,
        file_transaction(_person_overlay_path(slug)) as o_txn,
    ):
        global_raw = _upcast_mapping(load_mapping(g_txn.read_text(), GLOBAL_CONFIG_PATH), GLOBAL_CONFIG_PATH)
        overlay_path = _person_overlay_path(slug)
        overlay_raw = _upcast_mapping(load_mapping(o_txn.read_text(), overlay_path), overlay_path)
    return _person_view(slug, global_raw, overlay_raw)


def _read_company(ref: SubjectRef) -> SubjectView:
    assert ref.instance is not None
    slug = ref.instance
    path = _company_path(slug)
    with file_transaction(path) as transaction:
        if not path.exists():
            raise SubjectNotFound(f"company '{slug}' is not registered")
        raw = _upcast_mapping(load_mapping(transaction.read_text(), path), path)
    return _company_view(slug, raw)


def _read_project(ref: SubjectRef) -> SubjectView:
    assert ref.instance is not None
    slug = ref.instance
    path = _project_path(slug)
    with file_transaction(path) as transaction:
        if not path.exists():
            raise SubjectNotFound(f"project '{slug}' has no declared configuration")
        raw = _upcast_mapping(load_mapping(transaction.read_text(), path), path)
    return _project_view(slug, raw)


_READ_SUBJECT: dict[ConfigSubjectKind, Callable[[SubjectRef], SubjectView]] = {
    ConfigSubjectKind.COMPUTER: _read_computer,
    ConfigSubjectKind.GLOBAL: _read_global,
    ConfigSubjectKind.PERSON: _read_person,
    ConfigSubjectKind.COMPANY: _read_company,
    ConfigSubjectKind.PROJECT: _read_project,
}


def read_subject(ref: SubjectRef) -> SubjectView:
    """Read the current view of one addressed subject."""
    return _READ_SUBJECT[ref.kind](ref)


# --- init_subject ---


def _init_computer(_ref: SubjectRef, _fields: Mapping[str, object] | None, evidence: OwnEvidence) -> SubjectView:
    ensure_machine_config(_computer_source())
    evidence.mark(target_id(ConfigSubjectKind.COMPUTER, None, TargetDocument.MACHINE))
    return _read_computer(SubjectRef(ConfigSubjectKind.COMPUTER))


def _init_global(ref: SubjectRef, _fields: Mapping[str, object] | None, evidence: OwnEvidence) -> SubjectView:
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        stored = load_mapping(transaction.read_text(), GLOBAL_CONFIG_PATH)
        current = dict(upcast(stored, ref))
        if not GLOBAL_CONFIG_PATH.exists() or current != stored:
            _validate_global_candidate(current)
            carry_resource_migrations(stored, ref, evidence)
            transaction.replace_text(render_declared_config(ConfigKind.GLOBAL, current))
            evidence.mark(target_id(ConfigSubjectKind.GLOBAL, None, TargetDocument.REGISTRY))
    return _read_global(SubjectRef(ConfigSubjectKind.GLOBAL))


def _init_person(_ref: SubjectRef, fields: Mapping[str, object] | None, evidence: OwnEvidence) -> SubjectView:
    """Converge a person by its supplied or name-derived lookup key.

    Initialization may migrate the global people registry before lookup. A
    matching entry is returned without applying identity values from this
    payload; a new entry is appended to the registry.
    """
    fields = fields or {}
    requested_slug = fields.get(_SLUG_KEY)
    lookup_key = _person_init_lookup_key(fields)

    with file_transaction(GLOBAL_CONFIG_PATH) as g_txn:
        committed_text = g_txn.read_text()
        global_stored = load_mapping(committed_text, GLOBAL_CONFIG_PATH)
        global_ref = SubjectRef(ConfigSubjectKind.GLOBAL)
        global_raw = dict(upcast(global_stored, global_ref))
        people_raw = raw_people(global_raw)
        existing = _find_person_raw(people_raw, lookup_key) if lookup_key else None

        if existing is not None:
            assert lookup_key is not None
            slug = lookup_key
        else:
            name = fields.get("name")
            email = fields.get("email")
            if not name or not email:
                raise InvalidCandidate("person init requires `name` and `email` for a new person")
            reserved = {
                str(entry[_SLUG_KEY]) for entry in people_raw if isinstance(entry, dict) and entry.get(_SLUG_KEY)
            }
            base_slug = normalize_slug(str(requested_slug)) if requested_slug else normalize_slug(str(name))
            slug = ensure_unique_slug(PEOPLE_DIR, base_slug, reserved=reserved)
            raw_role = fields.get("role")
            raw_username = fields.get("username")
            entry = PersonEntry.model_validate(
                {
                    "name": str(name),
                    "email": str(email),
                    "slug": slug,
                    **({"role": raw_role} if raw_role else {}),
                    **({"username": raw_username} if raw_username else {}),
                }
            )
            candidate_raw = with_person(cast(dict[object, object], global_raw), entry)
            candidate_document = {
                str(key): value for key, value in candidate_raw.items() if key != _KIND_KEY
            }  # guard: loose-dict - raw YAML config
            _validate_global_candidate(candidate_document)
            carry_resource_migrations(global_stored, global_ref, evidence)
            commit_documents(
                [CommitEntry(g_txn, committed_text, render_declared_config(ConfigKind.GLOBAL, candidate_document))]
            )
            evidence.mark(target_id(ConfigSubjectKind.GLOBAL, None, TargetDocument.REGISTRY))

    display_name = existing.get("name") if existing is not None else fields.get("name")
    evidence.enter_unobserved()
    scaffold_personal_workspace(slug, str(display_name) if display_name else None)
    return _read_person(SubjectRef(ConfigSubjectKind.PERSON, slug))


def _init_company(_ref: SubjectRef, fields: Mapping[str, object] | None, evidence: OwnEvidence) -> SubjectView:
    fields = fields or {}
    name = fields.get("name")
    if not name:
        raise InvalidCandidate("company init requires `name`")
    slug = fields.get(_SLUG_KEY)
    evidence.enter_unobserved()
    company_dir = scaffold_company(str(name), str(slug) if slug else None)
    evidence.mark(target_id(ConfigSubjectKind.COMPANY, company_dir.name, TargetDocument.ROSTER))
    return _read_company(SubjectRef(ConfigSubjectKind.COMPANY, company_dir.name))


_INIT_SUBJECT: dict[
    ConfigSubjectKind, Callable[[SubjectRef, Mapping[str, object] | None, OwnEvidence], SubjectView]
] = {
    ConfigSubjectKind.COMPUTER: _init_computer,
    ConfigSubjectKind.GLOBAL: _init_global,
    ConfigSubjectKind.PERSON: _init_person,
    ConfigSubjectKind.COMPANY: _init_company,
}


def _try_revision_before(kind: ConfigSubjectKind, instance: str | None) -> str | None:
    """Opportunistically read a subject's current revision, tolerating absence."""
    if instance is None:
        return None
    try:
        return read_subject(SubjectRef(kind, instance)).revision
    except SubjectNotFound:
        return None


def init_subject(
    ref: SubjectRef,
    fields: Mapping[str, object] | None = None,
    *,
    request_id: str | None = None,
) -> SubjectView:
    """Converge one subject's backing document without overwriting existing values.

    `fields` carries init-time payload data person and company init consume
    (name, email, role, username, slug); computer and global ignore it.
    Project init is not reachable through this dispatch — it addresses "the
    caller's checkout", a filesystem context no `SubjectRef` carries, so the
    CLI edge calls `init_project_subject(root)` directly for that kind.
    """
    # For person/company, the caller addresses `init` with no instance yet; person init
    # can also derive its lookup key from the name before deciding whether it converges.
    probe_instance = ref.instance
    if probe_instance is None and fields:
        supplied_slug = fields.get(_SLUG_KEY)
        if supplied_slug:
            probe_instance = str(supplied_slug)
    no_slug_person = (
        ref.instance is None and ref.kind is ConfigSubjectKind.PERSON and not (fields and fields.get(_SLUG_KEY))
    )
    derived_instance = _person_init_lookup_key(fields) if no_slug_person else None
    person_key_derived = no_slug_person and fields is not None and _NAME_KEY in fields
    revision_before = None if no_slug_person else _try_revision_before(ref.kind, probe_instance)

    def compute(evidence: OwnEvidence) -> SubjectView:
        nonlocal probe_instance, revision_before
        if no_slug_person and derived_instance is not None and _person_is_registered(derived_instance):
            probe_instance = derived_instance
            revision_before = _try_revision_before(ref.kind, probe_instance)
        return _INIT_SUBJECT[ref.kind](ref, fields, evidence)

    view = run_observed(
        compute,
        request_id=request_id,
        kind=ref.kind,
        instance=probe_instance,
        operation=ResourceOperation.INIT,
        revision_before=revision_before,
        person_key_derived=person_key_derived,
    )
    outcome = ResourceChangeOutcome.UNCHANGED if view.revision == revision_before else ResourceChangeOutcome.COMMITTED
    emit_resource_change(
        request_id=request_id,
        kind=ref.kind,
        instance=view.ref.instance,
        operation=ResourceOperation.INIT,
        outcome=outcome,
        revision_before=revision_before,
        revision_after=view.revision,
        person_key_derived=person_key_derived,
        derived_key_matches_instance=(view.ref.instance == derived_instance) if derived_instance is not None else None,
    )
    return view


# --- affected_sections ---


def _affected_single(section: str, patch: Mapping[str, object]) -> frozenset[str]:
    return frozenset({section}) if patch else frozenset()


def _affected_person(patch: Mapping[str, object]) -> frozenset[str]:
    identity_patch, settings_patch = _split_person_patch(patch)
    affected: set[str] = set()
    if identity_patch:
        affected.add(_IDENTITY_SECTION)
    if settings_patch:
        affected.add(_SETTINGS_SECTION)
    return frozenset(affected)


_AFFECTED_SECTIONS: dict[ConfigSubjectKind, Callable[[Mapping[str, object]], frozenset[str]]] = {
    ConfigSubjectKind.COMPUTER: lambda patch: _affected_single(_COMPUTER_SECTION, patch),
    ConfigSubjectKind.GLOBAL: lambda patch: _affected_single(_GLOBAL_SECTION, patch),
    ConfigSubjectKind.PERSON: _affected_person,
    ConfigSubjectKind.COMPANY: lambda patch: _affected_single(_COMPANY_SECTION, patch),
    ConfigSubjectKind.PROJECT: lambda patch: _affected_single(_PROJECT_SECTION, patch),
}


def affected_sections(ref: SubjectRef, patch: Mapping[str, object]) -> frozenset[str]:
    """Return the section names one patch document touches."""
    return _AFFECTED_SECTIONS[ref.kind](patch)


# --- patch_subject ---


def _patch_computer(
    ref: SubjectRef, patch: Mapping[str, object], expected_revision: str, evidence: OwnEvidence
) -> SubjectView:
    # RFC 9110 ETag/If-Match-style comparison: `patch_machine_config_at` accepts the
    # historically wider `Mapping[object, object]` machine-input shape; a str-keyed
    # patch document is always a valid read of that wider shape.
    try:
        result = patch_machine_config_at(
            cast(Mapping[object, object], patch),
            expected_revision,
            delivered=delivery_recorder(ref, evidence),
        )
    except ReadOnlyDeclaration as exc:
        # The computer view already excludes `kind` (`_computer_view_from`), so a patch
        # naming it is the same refusal every other kind gives a projected section.
        raise ReadOnlyProjection(str(exc)) from exc
    return _computer_view(result)


def _patch_global(
    ref: SubjectRef, patch: Mapping[str, object], expected_revision: str, evidence: OwnEvidence
) -> SubjectView:
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        if not GLOBAL_CONFIG_PATH.exists():
            raise SubjectNotFound("global configuration has not been initialized")
        stored = load_mapping(transaction.read_text(), GLOBAL_CONFIG_PATH)
        raw = dict(upcast(stored, ref))
        actual_revision = _global_revision(raw)
        if actual_revision != expected_revision:
            raise StaleRevision(expected=expected_revision, actual=actual_revision)
        if _PEOPLE_KEY in patch:
            raise ReadOnlyProjection("the `people` section is a person-subject projection, not writable here")
        current_section = _global_section(raw)
        candidate_section = apply_merge_patch(current_section, patch)
        candidate_document: dict[str, object] = {  # guard: loose-dict - raw YAML config
            key: value for key, value in raw.items() if key != _KIND_KEY
        }
        candidate_document.update(candidate_section)
        _validate_global_candidate(candidate_document)
        carry_resource_migrations(stored, ref, evidence)
        transaction.replace_text(render_declared_config(ConfigKind.GLOBAL, candidate_document))
    return _global_view(candidate_document)


def _patch_person(
    ref: SubjectRef, patch: Mapping[str, object], expected_revision: str, evidence: OwnEvidence
) -> SubjectView:
    assert ref.instance is not None
    slug = ref.instance
    identity_patch, settings_patch = _split_person_patch(patch)
    overlay_path = _person_overlay_path(slug)
    with (
        file_transaction(GLOBAL_CONFIG_PATH) as g_txn,
        file_transaction(overlay_path) as o_txn,
    ):
        global_stored = load_mapping(g_txn.read_text(), GLOBAL_CONFIG_PATH)
        global_ref = SubjectRef(ConfigSubjectKind.GLOBAL)
        global_raw = dict(upcast(global_stored, global_ref))
        people_raw = raw_people(global_raw)
        index = next(
            (i for i, entry in enumerate(people_raw) if isinstance(entry, dict) and entry.get(_SLUG_KEY) == slug),
            None,
        )
        if index is None:
            raise SubjectNotFound(f"person '{slug}' is not registered")
        entry_raw = cast(dict[str, object], people_raw[index])  # guard: loose-dict - raw YAML config
        overlay_stored = load_mapping(o_txn.read_text(), overlay_path)
        overlay_raw = dict(upcast(overlay_stored, ref))

        identity = _person_identity_section(entry_raw)
        settings = _person_settings_section(overlay_raw)
        actual_revision = _person_revision(identity, settings)
        if actual_revision != expected_revision:
            raise StaleRevision(expected=expected_revision, actual=actual_revision)

        candidate_identity = apply_merge_patch(identity, identity_patch) if identity_patch else dict(identity)
        candidate_settings = apply_merge_patch(settings, settings_patch) if settings_patch else dict(settings)

        try:
            PersonEntry.model_validate({**candidate_identity, _SLUG_KEY: slug})
        except Exception as exc:
            raise InvalidCandidate(str(exc)) from exc
        try:
            PersonConfig.model_validate({**candidate_settings, _KIND_KEY: ConfigKind.PERSON.value, _SLUG_KEY: slug})
        except Exception as exc:
            raise InvalidCandidate(str(exc)) from exc

        candidate_people_raw = list(people_raw)
        candidate_people_raw[index] = {**candidate_identity, _SLUG_KEY: slug}
        candidate_global_document = {key: value for key, value in global_raw.items() if key != _KIND_KEY}
        candidate_global_document[_PEOPLE_KEY] = candidate_people_raw
        _validate_global_candidate(candidate_global_document)

        entry_targets = {
            g_txn.path: target_id(ConfigSubjectKind.GLOBAL, None, TargetDocument.REGISTRY),
            o_txn.path: target_id(ConfigSubjectKind.PERSON, slug, TargetDocument.OVERLAY),
        }
        try:
            carry_resource_migrations(global_stored, global_ref, evidence)
            carry_resource_migrations(overlay_stored, ref, evidence)
            commit_documents(
                [
                    CommitEntry(
                        g_txn,
                        g_txn.read_text(),
                        render_declared_config(ConfigKind.GLOBAL, candidate_global_document),
                    ),
                    CommitEntry(
                        o_txn,
                        o_txn.read_text(),
                        render_declared_config(ConfigKind.PERSON, {**candidate_settings, _SLUG_KEY: slug}),
                    ),
                ]
            )
        except PartialCommitFailure as exc:
            evidence.mark(*(entry_targets[path] for path in exc.failed_paths))
            raise
        evidence.mark(*entry_targets.values())

    return SubjectView(
        ref=ref,
        sources=(GLOBAL_CONFIG_PATH, overlay_path),
        sections={_IDENTITY_SECTION: candidate_identity, _SETTINGS_SECTION: candidate_settings},
        read_only={},
        revision=_person_revision(candidate_identity, candidate_settings),
    )


def _patch_company(
    ref: SubjectRef, patch: Mapping[str, object], expected_revision: str, _evidence: OwnEvidence
) -> SubjectView:
    assert ref.instance is not None
    slug = ref.instance
    path = _company_path(slug)
    with file_transaction(path) as transaction:
        if not path.exists():
            raise SubjectNotFound(f"company '{slug}' is not registered")
        stored = load_mapping(transaction.read_text(), path)
        raw = dict(upcast(stored, ref))
        current_section = _company_section(raw)
        actual_revision = view_revision({_COMPANY_SECTION: current_section})
        if actual_revision != expected_revision:
            raise StaleRevision(expected=expected_revision, actual=actual_revision)
        candidate_section = apply_merge_patch(current_section, patch)
        try:
            committed_model = CompanyConfig.model_validate(
                {**current_section, _KIND_KEY: ConfigKind.COMPANY.value, _SLUG_KEY: slug}
            )
            candidate_model = CompanyConfig.model_validate(
                {**candidate_section, _KIND_KEY: ConfigKind.COMPANY.value, _SLUG_KEY: slug}
            )
        except Exception as exc:
            raise InvalidCandidate(str(exc)) from exc
        validate_roster_candidate(slug, committed_model, candidate_model)
        carry_resource_migrations(stored, ref, _evidence)
        transaction.replace_text(render_declared_config(ConfigKind.COMPANY, candidate_section))
    return _company_view(slug, {**candidate_section, _SLUG_KEY: slug})


def _patch_project(
    ref: SubjectRef, patch: Mapping[str, object], expected_revision: str, _evidence: OwnEvidence
) -> SubjectView:
    assert ref.instance is not None
    slug = ref.instance
    path = _project_path(slug)
    with file_transaction(path) as transaction:
        if not path.exists():
            raise SubjectNotFound(f"project '{slug}' has no declared configuration")
        stored = load_mapping(transaction.read_text(), path)
        raw = dict(upcast(stored, ref))
        current_section = _project_section(raw)
        actual_revision = view_revision({_PROJECT_SECTION: current_section})
        if actual_revision != expected_revision:
            raise StaleRevision(expected=expected_revision, actual=actual_revision)
        candidate_section = apply_merge_patch(current_section, patch)
        try:
            ProjectConfig.model_validate({**candidate_section, _KIND_KEY: ConfigKind.PROJECT.value})
        except Exception as exc:
            raise InvalidCandidate(str(exc)) from exc
        # Written only — the project's own commit/review boundary governs afterward; this
        # engine never runs git.
        carry_resource_migrations(stored, ref, _evidence)
        transaction.replace_text(render_declared_config(ConfigKind.PROJECT, candidate_section))
    return _project_view(slug, {**candidate_section, _KIND_KEY: ConfigKind.PROJECT.value})


_PATCH_SUBJECT: dict[ConfigSubjectKind, Callable[[SubjectRef, Mapping[str, object], str, OwnEvidence], SubjectView]] = {
    ConfigSubjectKind.COMPUTER: _patch_computer,
    ConfigSubjectKind.GLOBAL: _patch_global,
    ConfigSubjectKind.PERSON: _patch_person,
    ConfigSubjectKind.COMPANY: _patch_company,
    ConfigSubjectKind.PROJECT: _patch_project,
}


def _patch_subject(
    ref: SubjectRef, patch: Mapping[str, object], expected_revision: str, evidence: OwnEvidence
) -> SubjectView:
    """Refuse migration-owned metadata before dispatching a kind-specific patch."""
    if _SCHEMA_VERSION_KEY in patch:
        raise ReadOnlyProjection(_READ_ONLY_SCHEMA_VERSION_ERROR)
    return _PATCH_SUBJECT[ref.kind](ref, patch, expected_revision, evidence)


def patch_subject(
    ref: SubjectRef,
    patch: Mapping[str, object],
    *,
    expected_revision: str,
    request_id: str | None = None,
) -> SubjectView:
    """Apply a merge-patch to one subject, refusing a stale or invalid candidate."""
    sections = affected_sections(ref, patch)
    view = run_observed(
        lambda evidence: _patch_subject(ref, patch, expected_revision, evidence),
        request_id=request_id,
        kind=ref.kind,
        instance=ref.instance,
        operation=ResourceOperation.PATCH,
        revision_before=expected_revision,
        sections=sections,
    )
    outcome = ResourceChangeOutcome.UNCHANGED if view.revision == expected_revision else ResourceChangeOutcome.COMMITTED
    emit_resource_change(
        request_id=request_id,
        kind=ref.kind,
        instance=ref.instance,
        operation=ResourceOperation.PATCH,
        outcome=outcome,
        revision_before=expected_revision,
        revision_after=view.revision,
        sections=sections,
    )
    return view


def remove_person_subject(
    ref: SubjectRef,
    *,
    delete_dir: bool = False,
    request_id: str | None = None,
) -> RosterOutcome:
    """Remove a person subject: clears the global entry and every roster reference.

    A separate top-level verb rather than a `remove=True` flag on `patch_subject`:
    removal returns a `RosterOutcome` (companies written, assignments removed),
    which shares no shape with `SubjectView`, so overloading the uniform patch
    dispatch would force every other kind's patch path to account for a return
    type it never produces.
    """
    assert ref.instance is not None
    slug = ref.instance
    outcome = run_observed(
        lambda evidence: _remove_person_subject(slug, evidence, delete_dir=delete_dir),
        request_id=request_id,
        kind=ConfigSubjectKind.PERSON,
        instance=slug,
        operation=ResourceOperation.REMOVE,
        revision_before=None,
    )
    emit_resource_change(
        request_id=request_id,
        kind=ConfigSubjectKind.PERSON,
        instance=slug,
        operation=ResourceOperation.REMOVE,
        outcome=ResourceChangeOutcome.COMMITTED,
        revision_before=None,
        revision_after=None,
        companies_written=outcome.companies_written,
        removed_assignments=outcome.removed_assignments,
    )
    return outcome


def _remove_person_subject(slug: str, evidence: OwnEvidence, *, delete_dir: bool) -> RosterOutcome:
    overlay_path = _person_overlay_path(slug)
    company_paths = sorted(list_company_config_paths())

    with ExitStack() as stack:
        g_txn = stack.enter_context(file_transaction(GLOBAL_CONFIG_PATH))
        # Held for mutual exclusion against a concurrent read/patch of this person while
        # removal is in flight; removal itself never writes the overlay document.
        stack.enter_context(file_transaction(overlay_path))
        company_txns = [(path.parent.name, stack.enter_context(file_transaction(path))) for path in company_paths]

        committed_global_text = g_txn.read_text()
        global_stored = load_mapping(committed_global_text, GLOBAL_CONFIG_PATH)
        global_ref = SubjectRef(ConfigSubjectKind.GLOBAL)
        global_raw = dict(upcast(global_stored, global_ref))
        if _find_person_raw(raw_people(global_raw), slug) is None:
            raise SubjectNotFound(f"person '{slug}' is not registered")

        committed_companies: dict[str, CompanyConfig] = {}
        committed_texts: dict[str, str] = {}
        stored_company_documents: dict[str, Mapping[str, object]] = {}
        for company_slug, txn in company_txns:
            text = txn.read_text()
            committed_texts[company_slug] = text
            stored_company = load_mapping(text, txn.path)
            stored_company_documents[company_slug] = stored_company
            company_ref = SubjectRef(ConfigSubjectKind.COMPANY, company_slug)
            raw = dict(upcast(stored_company, company_ref))
            committed_companies[company_slug] = CompanyConfig.model_validate(
                {**raw, _KIND_KEY: ConfigKind.COMPANY.value, _SLUG_KEY: company_slug}
            )

        candidate_global_raw = without_person(cast(dict[object, object], global_raw), slug)
        candidate_global_document = {
            str(key): value for key, value in candidate_global_raw.items() if key != _KIND_KEY
        }  # guard: loose-dict - raw YAML config
        _validate_global_candidate(candidate_global_document)
        changed_companies, outcome = rosters_without_person(committed_companies, slug)

        entries = [
            CommitEntry(
                g_txn,
                committed_global_text,
                render_declared_config(ConfigKind.GLOBAL, candidate_global_document),
            )
        ]
        entry_targets = {g_txn.path: target_id(ConfigSubjectKind.GLOBAL, None, TargetDocument.REGISTRY)}
        company_txns_by_slug = dict(company_txns)
        for company_slug, company_config in changed_companies.items():
            txn = company_txns_by_slug[company_slug]
            candidate_document = company_config.model_dump(mode="json", exclude_defaults=True)
            candidate_document.pop(_KIND_KEY, None)
            candidate_document.pop(_SLUG_KEY, None)
            entries.append(
                CommitEntry(
                    txn,
                    committed_texts[company_slug],
                    render_declared_config(ConfigKind.COMPANY, candidate_document),
                )
            )
            entry_targets[txn.path] = target_id(ConfigSubjectKind.COMPANY, company_slug, TargetDocument.ROSTER)
        try:
            carry_resource_migrations(global_stored, global_ref, evidence)
            for company_slug in changed_companies:
                company_ref = SubjectRef(ConfigSubjectKind.COMPANY, company_slug)
                carry_resource_migrations(stored_company_documents[company_slug], company_ref, evidence)
            commit_documents(entries)
        except PartialCommitFailure as exc:
            evidence.mark(*(entry_targets[path] for path in exc.failed_paths))
            raise
        evidence.mark(*entry_targets.values())

    if delete_dir:
        person_dir = PEOPLE_DIR / slug
        if person_dir.exists():
            evidence.enter_unobserved()
            shutil.rmtree(person_dir)

    return outcome


def init_project_subject(
    root: Path,
    *,
    request_id: str | None = None,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
) -> SubjectView:
    """Adopt the caller's folder and return its declared subject view.

    Not reachable through `init_subject`: folder adoption addresses a
    filesystem context no `SubjectRef` carries before its identity is derived.

    The setup operation determines the declared tier. Project folders return
    their catalog view; person and company homes return their corresponding
    configuration subject view.
    """
    config_path = root.expanduser().resolve() / ConfigFileName.OVERLAY
    kind = load_declared_config_kind(config_path) if config_path.is_file() else ConfigKind.PROJECT
    subject_kind = ConfigSubjectKind(kind.value)
    if kind in (ConfigKind.PERSON, ConfigKind.COMPANY):
        identity = root.name
    elif kind is ConfigKind.PROJECT:
        identity = get_project_slug(root)
    else:
        identity = None
    revision_before = _try_revision_before(subject_kind, identity)

    result: ProjectInitializationResult | None = None

    def _compute(evidence: OwnEvidence) -> SubjectView:
        nonlocal result
        evidence.enter_unobserved()
        result = init_project(root, trigger=trigger)
        ref = SubjectRef(ConfigSubjectKind(result.kind.value), result.identity)
        evidence.mark(target_id(ref.kind, ref.instance, TargetDocument.REGISTRY))
        if result.kind is ConfigKind.PROJECT:
            evidence.mark(target_id(ref.kind, ref.instance, TargetDocument.PLUMBING))
            catalog = get_project_catalog_service()
            catalog.refresh()
            node = catalog.get_by_slug(result.identity)
            if node is None:
                raise SubjectNotFound(f"project at {root} did not register after init")
            ref = SubjectRef(ConfigSubjectKind.PROJECT, node.slug)
        return read_subject(ref)

    view = run_observed(
        _compute,
        request_id=request_id,
        kind=subject_kind,
        instance=identity,
        operation=ResourceOperation.INIT,
        revision_before=revision_before,
    )
    emit_resource_change(
        request_id=request_id,
        kind=view.ref.kind,
        instance=view.ref.instance,
        operation=ResourceOperation.INIT,
        outcome=ResourceChangeOutcome.UNCHANGED
        if result is not None and result.already_registered and revision_before == view.revision
        else ResourceChangeOutcome.COMMITTED,
        revision_before=revision_before,
        revision_after=view.revision,
    )
    return view
