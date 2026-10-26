"""Configuration file loading and validation."""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ValidationError

from teleclaude.config._environment import (
    company_environment_creation_mode,
    expand_environment_references,
    find_environment_references,
    read_environment_file,
    reconcile_environment_references,
    replace_environment_value,
    replace_environment_values,
    require_owner_only_environment,
    write_environment_values,
)
from teleclaude.config._unresolved import NO_OVERRIDES, drop_unresolved_fields
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.context_root import declared_config_kind, load_declared_config_kind, resolve_context_root
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.errors import (
    ConfigLoadError,
    ConfigNotReadyError,
    cause_findings,
    describe_load_error,
    load_error_findings,
)
from teleclaude.config.field_constraints import (
    MACHINE_CONTEXT_KEY,
    UNRESOLVED_CONTEXT_KEY,
    refuses_only_unmet_requirements,
)
from teleclaude.config.github_schema import require_bare_github_key_references
from teleclaude.config.identity_schema import CompanyMember, PersonEntry
from teleclaude.config.inbound_secret_references import require_inbound_secret_references
from teleclaude.config.machine import config as machine_config
from teleclaude.config.migrations._carry import carry_pending
from teleclaude.config.migrations._chain import Destination, RegistrySubjectRequired, upcast
from teleclaude.config.migrations._registry import registered_subject
from teleclaude.config.migrations.read import upcast_for_read
from teleclaude.config.project_home import require_home_owner
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.config.schema import (
    TIER_DOCUMENT_MODELS,
    AppConfig,
    CompanyConfig,
    ConfigKind,
    GlobalConfig,
    MailAccount,
    OutputVisibilitySettings,
    PersonConfig,
    ProjectConfig,
    TierDocument,
)
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.roles import RoleName, composite_role
from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, PEOPLE_DIR, ConfigFileName
from teleclaude.slug import validate_slug
from teleclaude.types.github_binding import GitHubActorAssignment

logger = get_logger(__name__)
_PERSON_SLUG_FIELD = "slug"
_UNRESOLVED_REFERENCES_EVENT = "config_references_unresolved_here"
_COMPANY_UNREADABLE_EVENT = "company_declaration_unreadable"
_PERSON_CLAIM_MISMATCH = "Person config claim '{claim}' does not match save target '{target}'"
_UTF8 = "utf-8"
_CONTENT_READ_FAILURE = "Failed to read config content for {path}: {error}"
_VALIDATION_FAILURE = "Failed to validate config file {path}: {error}"
_NOT_READY_FAILURE = "Config file {path} is not ready on this computer: {error}"
_KIND_FIELD = "kind"
_SCHEMA_VERSION_FIELD = "schema_version"
_PROJECT_SAVE_REGISTRY_ERROR = "Project configuration saves require a registered project root"
_ADOPTED_METADATA_SUBJECT_ERROR = "Adopted metadata requires a registered overlay of the declared tier: {path}"
_ADOPTED_METADATA_NAME_FIELDS: dict[ConfigKind, str] = {
    ConfigKind.PROJECT: "project_name",
    ConfigKind.PERSON: "name",
    ConfigKind.COMPANY: "name",
}
_DESCRIPTION_FIELD = "description"
_STAGED_DECLARATION_YAML_ERROR = "{path}: invalid YAML: {error}"
_STAGED_DECLARATION_MAPPING_ERROR = "{path}: declaration must be a mapping"
_STAGED_DECLARATION_KIND_ERROR = "{path}: declaration kind must be one of: global, project, person, company"
_STAGED_DECLARATION_SCHEMA_ERROR = "{path}: invalid {kind} declaration: {error}"
_FINDINGS_SEPARATOR = "; "
_OWNER_ONLY_MODE = 0o600


@dataclass(frozen=True)
class ExpandedOverlayInput:
    """One overlay expanded from its sibling environment file when needed."""

    value: object
    environment_path: Path | None
    unresolved: Mapping[tuple[str | int, ...], str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedOverlay:
    """A tier document after reference resolution, with the references that have no value here."""

    value: object
    unresolved: Mapping[tuple[str | int, ...], str]


def expanded_overlay_input(path: Path, document: object, kind: ConfigKind) -> ExpandedOverlayInput:
    """Expand environment references using only the overlay's sibling `.env`."""
    if kind is ConfigKind.GLOBAL and isinstance(document, Mapping):
        require_bare_github_key_references(document)
    references = find_environment_references(document)
    if not references:
        return ExpandedOverlayInput(value=document, environment_path=None)
    environment_path = path.with_name(ConfigFileName.ENV)
    environment = read_environment_file(environment_path, owner_only=kind in (ConfigKind.COMPANY, ConfigKind.PERSON))
    resolved = resolve_overlay_references(document, environment, kind, path)
    return ExpandedOverlayInput(
        value=resolved.value,
        environment_path=environment_path,
        unresolved=resolved.unresolved,
    )


def resolve_overlay_references(
    document: object, environment: Mapping[str, str], kind: ConfigKind, path: Path
) -> ResolvedOverlay:
    """Expand a tier document's references from ``environment``; one with no value here leaves its field absent."""
    if kind is ConfigKind.GLOBAL and isinstance(document, Mapping):
        require_bare_github_key_references(document)
    expanded = expand_environment_references(document, environment, config_path=path, preserve_unresolved=True)
    unresolved = {
        reference.path: reference.name
        for reference in find_environment_references(document)
        if reference.name not in environment and reference.default is None
    }
    if unresolved:
        logger.debug(_UNRESOLVED_REFERENCES_EVENT, path=str(path), names=sorted(set(unresolved.values())))
    return ResolvedOverlay(
        value=drop_unresolved_fields(expanded, TIER_DOCUMENT_MODELS[kind], NO_OVERRIDES),
        unresolved=unresolved,
    )


def validate_tier_document[T: BaseModel](model_class: type[T], value: object) -> T:
    """Validate a resolved tier document's shape and field relationships, the same on every computer."""
    return model_class.model_validate(value)


def validate_tier_readiness[T: BaseModel](
    model_class: type[T], value: object, unresolved: Mapping[tuple[str | int, ...], str]
) -> T:
    """Validate a resolved tier document and judge that this computer holds every value its role needs."""
    return model_class.model_validate(
        value,
        context={MACHINE_CONTEXT_KEY: machine_config, UNRESOLVED_CONTEXT_KEY: unresolved},
    )


def _read_locked_overlay(
    transaction: FileTransaction, path: Path
) -> dict[str, Any]:  # guard: loose-dict - raw YAML config
    """Read one already-locked overlay document as a typed dynamic mapping."""
    content = transaction.read_text(encoding=_UTF8)
    parsed: object = round_trip_yaml().load(content) if content else {}
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, Mapping):
        raise ValueError(f"Configuration document must be a mapping: {path}")
    return {str(key): value for key, value in parsed.items()}


def _ignore_migration_delivery(_destination: Destination) -> None:
    """Keep migration destinations outside ordinary loader save results."""


def _validate_overlay_candidate(
    path: Path,
    kind: ConfigKind,
    document: Mapping[str, object],
    subject: SubjectRef,
    environment_updates: Mapping[str, str],
) -> None:  # guard: loose-dict - pydantic input from arbitrary YAML
    """Validate the complete current document before a writer delivers migrations."""
    candidate = dict(document)
    if kind is ConfigKind.PERSON and subject.instance is not None:
        candidate.setdefault(_PERSON_SLUG_FIELD, subject.instance)
    validate_tier_candidate(path, kind, candidate, environment_updates)


def validate_tier_candidate(
    path: Path,
    kind: ConfigKind,
    candidate: Mapping[str, object],
    environment_updates: Mapping[str, str] | None = None,
    *,
    environment_override: Mapping[str, str] | None = None,
) -> TierDocument:  # guard: loose-dict - pydantic input from arbitrary YAML
    """Validate a tier document a writer is about to persist at ``path``, exactly as loading it will.

    References resolve from the environment file beside ``path`` together with the values the
    writer is about to store there, and the document is judged alone: whether this computer holds
    the values its role needs is its readiness, which ``validate_declaration_file`` judges.
    """
    document = {**candidate, _KIND_FIELD: kind.value}
    require_inbound_secret_references(path, document)
    if kind is ConfigKind.GLOBAL:
        require_bare_github_key_references(document)
    environment: dict[str, str] = {}
    if environment_override is not None:
        environment.update(environment_override)
    elif find_environment_references(document):
        environment = read_environment_file(
            path.with_name(ConfigFileName.ENV), owner_only=kind in (ConfigKind.COMPANY, ConfigKind.PERSON)
        )
    environment.update(environment_updates or {})
    resolved = resolve_overlay_references(document, environment, kind, path)
    return validate_tier_document(TIER_DOCUMENT_MODELS[kind], resolved.value)


class DeclaredMailAccountRefusal(StrEnum):
    """Closed reasons a named person account cannot be resolved."""

    MISSING_REGISTERED_SLUG = "missing_registered_slug"
    CANONICAL_DOCUMENT_MISSING = "canonical_document_missing"
    PERSISTED_CLAIM_MISMATCH = "persisted_claim_mismatch"
    ACCOUNT_NOT_DECLARED = "account_not_declared"


@dataclass(frozen=True)
class ResolvedDeclaredMailAccount:
    """A canonical person document's declared account and state root."""

    account: MailAccount
    state_root: Path


@dataclass(frozen=True)
class RefusedDeclaredMailAccount:
    """A closed refusal from canonical declared-account resolution."""

    reason: DeclaredMailAccountRefusal


DeclaredMailAccountResolution = ResolvedDeclaredMailAccount | RefusedDeclaredMailAccount


def load_config[T: BaseModel](
    path: Path,
    model_class: type[T],
    kind: ConfigKind,
    root: Path,
    *,
    default_fields: Mapping[str, object] | None = None,
) -> T:
    """Load YAML config from ``path`` and validate it with ``model_class``.

    Args:
        path: Path to a configuration YAML file.
        model_class: The Pydantic model class to use for validation.

    Returns:
        The validated configuration model.
    """
    defaults = {"kind": kind, **(default_fields or {})}
    if not path.exists():
        return model_class.model_validate(defaults)

    return _validated_model(path, _read_config_mapping(path), model_class, kind)


def _validated_model[T: BaseModel](
    path: Path, raw: object, model_class: type[T], kind: ConfigKind, *, readiness: bool = False
) -> T:
    """Validate one already-read declaration through the shared read pipeline.

    Loading judges the document; ``readiness`` also judges that this computer holds the values its role needs.
    """
    try:
        if not isinstance(raw, Mapping):
            return model_class.model_validate(raw)
        raw = upcast_for_read(path, raw)
        require_inbound_secret_references(path, raw)
        expanded = expanded_overlay_input(path, raw, kind)
        if readiness:
            return validate_tier_readiness(model_class, expanded.value, expanded.unresolved)
        return validate_tier_document(model_class, expanded.value)
    except ValidationError as exc:
        if readiness and refuses_only_unmet_requirements(exc):
            raise ConfigNotReadyError(_NOT_READY_FAILURE.format(path=path, error=exc), document=path) from exc
        raise ConfigLoadError(_VALIDATION_FAILURE.format(path=path, error=exc), document=path) from exc
    except Exception as exc:
        raise ConfigLoadError(_VALIDATION_FAILURE.format(path=path, error=exc), document=path) from exc


def validate_declaration_file(path: Path) -> None:
    """Judge one live tier declaration's readiness on this computer; raise ``ConfigLoadError`` when it fails.

    The document is validated as loading does, and every value this computer's role needs must resolve.
    """
    try:
        raw: object = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigLoadError(_CONTENT_READ_FAILURE.format(path=path, error=exc), document=path) from exc
    try:
        kind = declared_config_kind(path, raw)
    except ValueError as exc:
        raise ConfigLoadError(str(exc), document=path) from exc
    _validated_model(path, raw, TIER_DOCUMENT_MODELS[kind], kind, readiness=True)


def validate_staged_declaration(path: Path, content: bytes) -> list[str]:
    """Validate one staged declaration through the same pipeline that loads it.

    The staged bytes are migrated, their secret declarations checked, their references resolved
    from the environment file beside ``path`` on this computer, and their schema and declared field
    relationships judged. This computer's readiness is not judged at commit. No other file is validated.
    """
    try:
        raw = yaml.safe_load(content.decode(_UTF8))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return [_STAGED_DECLARATION_YAML_ERROR.format(path=path, error=_FINDINGS_SEPARATOR.join(cause_findings(exc)))]
    if not isinstance(raw, Mapping):
        return [_STAGED_DECLARATION_MAPPING_ERROR.format(path=path)]
    try:
        kind = ConfigKind(raw.get(_KIND_FIELD))
    except (TypeError, ValueError):
        return [_STAGED_DECLARATION_KIND_ERROR.format(path=path)]

    try:
        _validated_model(path, raw, TIER_DOCUMENT_MODELS[kind], kind)
    except ConfigLoadError as exc:
        findings = _FINDINGS_SEPARATOR.join(load_error_findings(exc))
        return [_STAGED_DECLARATION_SCHEMA_ERROR.format(path=path, kind=kind.value, error=findings)]
    return []


def _read_config_mapping(path: Path) -> object:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        error = ConfigLoadError(f"Failed to read config file {path}: {e}", document=path)
        error.__cause__ = e
        logger.error("%s", describe_load_error(error))
        raise error from e


def load_project_config(path: Path) -> ProjectConfig:
    """Load project-level configuration.

    A declaration inside a person's or company's home must name that home's owner
    (`require_home_owner`); a missing declaration is the empty default and is not checked.
    """
    config = load_config(path, ProjectConfig, ConfigKind.PROJECT, path.parent)
    if path.exists():
        try:
            require_home_owner(
                path.parent, company=config.company, person=config.person, person_slugs=registered_person_slugs()
            )
        except ValueError as exc:
            if isinstance(exc, ConfigLoadError):
                raise
            raise ConfigLoadError(str(exc), document=path) from exc
    return config


def load_declared_project_config(root: Path) -> ProjectConfig | None:
    """Load the project configuration for a root declaring `kind: project`.

    Returns `None` when `root` carries no configuration file, or carries one
    declaring a tier other than project. Raises `ConfigLoadError` for a declaration
    that cannot be read or does not validate.
    """
    marker = root / ConfigFileName.OVERLAY
    if not marker.is_file():
        return None
    try:
        kind = load_declared_config_kind(marker)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
        raise ConfigLoadError(_CONTENT_READ_FAILURE.format(path=marker, error=exc), document=marker) from exc
    if kind is not ConfigKind.PROJECT:
        return None
    return load_project_config(marker)


def load_declared_project_config_from_content(path: Path, content: bytes) -> ProjectConfig | None:
    """Load the project configuration from declaration bytes read elsewhere, such as a committed tree.

    ``path`` is the declaration's live location, which identifies its registry subject
    and sibling environment file; ``content`` is what is validated. Returns `None`
    when the content declares a tier other than project, with the same contract as
    `load_declared_project_config`.
    """
    try:
        raw: object = yaml.safe_load(content.decode(_UTF8)) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(_CONTENT_READ_FAILURE.format(path=path, error=exc)) from exc
    if declared_config_kind(path, raw) is not ConfigKind.PROJECT:
        return None
    config = _validated_model(path, raw, ProjectConfig, ConfigKind.PROJECT)
    require_home_owner(
        path.parent, company=config.company, person=config.person, person_slugs=registered_person_slugs()
    )
    return config


def save_project_config(path: Path, config: ProjectConfig) -> None:
    """Save project config to disk using atomic write (temp + rename)."""
    data = project_config_document(config)
    subject = registered_subject(path)
    if subject is None or subject.kind is not ConfigSubjectKind.PROJECT:
        raise RegistrySubjectRequired(_PROJECT_SAVE_REGISTRY_ERROR)
    _write_overlay_config(path, ConfigKind.PROJECT, data, subject)


def project_config_document(config: ProjectConfig) -> dict[str, Any]:  # guard: loose-dict - Pydantic document output
    """Serialize a project config while retaining explicit capability decisions."""
    data = config.model_dump(mode="json", exclude_defaults=True)
    for capability in ("code", "docs", "agents"):
        value = getattr(config, capability)
        data[capability] = {"enabled": value.enabled}
    return data


def _model_to_dict(model: BaseModel) -> dict[str, Any]:  # guard: loose-dict - Pydantic model_dump output
    """Convert a Pydantic model to a dict suitable for YAML serialization."""
    return model.model_dump(mode="json", exclude_defaults=True)


def _deep_merge(
    base: dict[str, Any],  # guard: loose-dict - recursive merge of arbitrary YAML
    overlay: dict[str, Any],  # guard: loose-dict - recursive merge of arbitrary YAML
) -> dict[str, Any]:  # guard: loose-dict - recursive merge of arbitrary YAML
    """Recursively merge overlay into base, returning a new dict."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def save_global_config(config: GlobalConfig, path: Path | None = None) -> None:
    """Atomic merge-write of global config.

    Reads the existing file first and merges model fields on top, preserving
    keys that are not part of the GlobalConfig schema (e.g. jobs, deployment).
    """
    target = path or GLOBAL_CONFIG_PATH
    subject = SubjectRef(ConfigSubjectKind.GLOBAL)
    with file_transaction(target) as transaction:
        stored = _read_locked_overlay(transaction, target)
        current = dict(upcast(stored, subject))
        overlay = _model_to_dict(config)
        merged = _deep_merge(current, overlay)
        reconciled, environment_updates = _reconcile_overlay_document(
            target, ConfigKind.GLOBAL, merged, existing_document=current
        )
        _validate_overlay_candidate(target, ConfigKind.GLOBAL, reconciled, subject, environment_updates)
        carry_pending(stored, subject, delivered=_ignore_migration_delivery)
        transaction.replace_text(render_declared_config(ConfigKind.GLOBAL, reconciled))
    _write_overlay_environment(target, ConfigKind.GLOBAL, environment_updates)
    logger.info("Saved global config to %s (merged, preserved %d existing keys)", target, len(stored))


def save_person_config(slug: str, config: PersonConfig) -> None:
    """Atomic write of per-person config keyed by slug. Creates directory if needed."""
    validate_slug(slug)
    if config.slug != slug:
        raise ValueError(_PERSON_CLAIM_MISMATCH.format(claim=config.slug, target=slug))
    person_dir = PEOPLE_DIR / slug
    person_dir.mkdir(parents=True, exist_ok=True)
    target = person_dir / ConfigFileName.OVERLAY
    subject = SubjectRef(ConfigSubjectKind.PERSON, slug)
    data = _model_to_dict(config)
    _write_overlay_config(target, ConfigKind.PERSON, data, subject)
    logger.info("Saved person config for %s to %s", slug, target)


def load_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global-level configuration."""
    if path is None:
        path = GLOBAL_CONFIG_PATH
    return load_config(path, GlobalConfig, ConfigKind.GLOBAL, path.parent)


def read_global_config_transaction(transaction: FileTransaction) -> GlobalConfig:
    """Validate the latest global declaration through its already-held lock."""
    if not transaction.path.exists():
        return GlobalConfig(kind=ConfigKind.GLOBAL)
    raw = _read_config_mapping(transaction.path)
    return _validated_model(transaction.path, raw, GlobalConfig, ConfigKind.GLOBAL)


def global_environment_creation_mode(
    declaration: GlobalConfig, transaction: FileTransaction, names: Iterable[str]
) -> int | None:
    """Apply declared App-key custody while the declaration and environment locks are held."""
    protected = {profile.private_key_base64_env for profile in declaration.github.apps}
    if not protected.intersection(names):
        return None
    if transaction.path.exists():
        require_owner_only_environment(transaction.path)
    return _OWNER_ONLY_MODE


@contextmanager
def _global_environment_write(
    names: Iterable[str], declaration_path: Path = GLOBAL_CONFIG_PATH
) -> Iterator[tuple[FileTransaction, int | None]]:
    """Hold the existing global locks across current classification and mutation."""
    with file_transaction(declaration_path) as declaration_transaction:
        declaration = read_global_config_transaction(declaration_transaction)
        with file_transaction(declaration_path.with_name(ConfigFileName.ENV)) as environment_transaction:
            creation_mode = global_environment_creation_mode(declaration, environment_transaction, names)
            yield environment_transaction, creation_mode


def update_global_environment(name: str, value: str | None) -> None:
    """Keep single-key set/clear semantics under declaration-then-environment locks."""
    with _global_environment_write((name,)) as (transaction, creation_mode):
        if creation_mode is not None and not transaction.path.exists() and value is None:
            return
        replace_environment_value(transaction, name, value, creation_mode=creation_mode)


def github_actor_for_role(role: RoleName) -> GitHubActorAssignment | None:
    """Answer a configured declaration for the actual role; confer no caller authority."""
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        declaration = read_global_config_transaction(transaction)
        app_id = declaration.github.roles.get(role, declaration.github.roles.get(composite_role(role)))
        return next(
            (profile.assignment for profile in declaration.github.apps if profile.assignment.app_id == app_id), None
        )


def github_actor_inventory() -> tuple[GitHubActorAssignment, ...]:
    """List every App the machine's inventory declares, in declaration order."""
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        declaration = read_global_config_transaction(transaction)
        return tuple(profile.assignment for profile in declaration.github.apps)


def github_actor_for_app_id(app_id: int) -> GitHubActorAssignment | None:
    """Resolve a project-selected App from the locked global declaration."""
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        declaration = read_global_config_transaction(transaction)
        return next(
            (profile.assignment for profile in declaration.github.apps if profile.assignment.app_id == app_id), None
        )


def load_person_config(path: Path, *, registered_slug: str | None = None) -> PersonConfig:
    """Load per-person configuration."""
    default_fields = {_PERSON_SLUG_FIELD: registered_slug} if registered_slug is not None else None
    return load_config(
        path,
        PersonConfig,
        ConfigKind.PERSON,
        path.parent,
        default_fields=default_fields,
    )


def load_company_config(path: Path) -> CompanyConfig:
    """Load company-tier configuration."""
    return load_config(path, CompanyConfig, ConfigKind.COMPANY, path.parent)


def registered_person_slugs() -> frozenset[str]:
    """Answer the slugs of the people the global configuration registers."""
    return frozenset(person.slug for person in load_global_config().people if person.slug)


def company_memberships(person_slug: str, companies_root: Path | None = None) -> dict[str, CompanyMember]:
    """Answer one person's declared membership in each company, keyed by company slug.

    A company whose declaration does not load is logged and contributes no membership, so it
    grants nothing; the person's memberships in readable companies are still answered.
    """
    memberships: dict[str, CompanyMember] = {}
    for config_path in list_company_config_paths(companies_root):
        company_slug = config_path.parent.name
        try:
            company = load_company_config(config_path)
        except ValueError as exc:
            logger.warning(_COMPANY_UNREADABLE_EVENT, company=company_slug, path=str(config_path), error=str(exc))
            continue
        member = company.members.get(person_slug)
        if member is not None:
            memberships[company_slug] = member
    return memberships


def _company_dir(slug: str, companies_root: Path | None) -> Path:
    """Resolve a company folder, validating the slug *before* building the path.

    The slug comes from config or a caller and is interpolated into a filesystem
    path; validating it against the kebab-case slug contract first rejects path
    traversal (``../``) and other malformed input before any path is constructed.
    ``companies_root`` resolves at call time from the module global when not given,
    so the location stays monkeypatchable (mirrors the per-person tier).
    """
    validate_slug(slug)
    root = companies_root if companies_root is not None else COMPANIES_ROOT
    return root / slug


def save_company_config(slug: str, config: CompanyConfig, companies_root: Path | None = None) -> None:
    """Atomic write of the company config keyed by slug. Creates the folder if needed."""
    company_dir = _company_dir(slug, companies_root)
    company_dir.mkdir(parents=True, exist_ok=True)
    _write_overlay_config(
        company_dir / ConfigFileName.OVERLAY,
        ConfigKind.COMPANY,
        _model_to_dict(config),
        SubjectRef(ConfigSubjectKind.COMPANY, slug),
    )
    logger.info("Saved company config for %s", slug)


def list_company_config_paths(companies_root: Path | None = None) -> list[Path]:
    """List folder-discovered company overlay paths, sorted by slug.

    Discovery without loading, so a caller that must survive a malformed company
    — validation especially — can enumerate the full roster and load each entry
    under its own error handling. ``list_company_configs`` loads eagerly and
    therefore surfaces the first failure instead of the roster.
    """
    root = companies_root if companies_root is not None else COMPANIES_ROOT
    if not root.exists():
        return []
    return sorted(root.glob(f"*/{ConfigFileName.OVERLAY}"))


def list_company_configs(companies_root: Path | None = None) -> list[tuple[str, CompanyConfig]]:
    """List folder-discovered companies as ``(slug, CompanyConfig)`` pairs, sorted by slug."""
    return [
        (config_path.parent.name, load_company_config(config_path))
        for config_path in list_company_config_paths(companies_root)
    ]


def find_company_config_path(slug: str, companies_root: Path | None = None) -> Path | None:
    """Find a company's ``teleclaude.yml`` by slug-named folder under ``COMPANIES_ROOT``.

    Folder-discovery only: the slug is the company id and the folder name. No
    registry file — the ``COMPANIES_ROOT`` tree is the registry. Mirrors the
    per-person tier's discovery.
    """
    config_path = _company_dir(slug, companies_root) / ConfigFileName.OVERLAY
    return config_path if config_path.exists() else None


def load_company_config_for_slug(slug: str, companies_root: Path | None = None) -> CompanyConfig | None:
    """Load the company config for a slug when its folder is present."""
    company_config_path = find_company_config_path(slug, companies_root)
    if company_config_path is None:
        return None
    return load_company_config(company_config_path)


def load_company_credentials(slug: str, companies_root: Path | None = None) -> dict[str, str]:
    """Resolve a company's service credentials through the single resolver seam.

    Reads the company-folder ``.env`` (``companies/<slug>/.env``; unprefixed keys —
    the directory is the namespace) via the existing ``${VAR}`` mechanism. This is
    the one seam every call site uses; it is swappable to a real secrets service
    later without touching callers. The company is located by ``slug`` alone — no
    environment variable names its location.

    Security contract:

    - A company with no ``.env`` has no credentials and yields an empty mapping.
    - The ``.env`` must be owner-only (mode ``0600``); a group/world-readable file
      exposes secrets and raises ``CompanyCredentialsError`` rather than loading.
    - An unreadable ``.env`` raises ``CompanyCredentialsError`` rather than silently
      returning empty credentials.
    """
    env_path = _company_dir(slug, companies_root) / ConfigFileName.ENV
    return read_environment_file(env_path, owner_only=True)


def _write_overlay_config(
    path: Path,
    kind: ConfigKind,
    document: dict[str, Any],  # guard: loose-dict - Pydantic model_dump output
    subject: SubjectRef,
) -> None:
    """Persist one overlay after carrying its registry subject's pending migrations."""
    with file_transaction(path) as transaction:
        stored = _read_locked_overlay(transaction, path)
        current = dict(upcast(stored, subject))
        reconciled, environment_updates = _reconcile_overlay_document(path, kind, document, existing_document=current)
        _validate_overlay_candidate(path, kind, reconciled, subject, environment_updates)
        carry_pending(stored, subject, delivered=_ignore_migration_delivery)
        transaction.replace_text(render_declared_config(kind, reconciled))
    _write_overlay_environment(path, kind, environment_updates)


def carry_adopted_metadata(
    path: Path,
    kind: ConfigKind,
    *,
    name: str | None,
    description: str | None,
) -> None:
    """Fill missing adopted-folder metadata under its tier-owned overlay lock."""
    name_field = _ADOPTED_METADATA_NAME_FIELDS.get(kind)
    subject = registered_subject(path)
    if name_field is None or subject is None or subject.kind.value != kind.value:
        raise RegistrySubjectRequired(_ADOPTED_METADATA_SUBJECT_ERROR.format(path=path))

    environment_updates: dict[str, str] = {}
    with file_transaction(path) as transaction:
        stored = _read_locked_overlay(transaction, path)
        current = dict(upcast(stored, subject))
        candidate = dict(current)
        if name is not None and candidate.get(name_field) is None:
            candidate[name_field] = name
        if description is not None and candidate.get(_DESCRIPTION_FIELD) is None:
            candidate[_DESCRIPTION_FIELD] = description
        if candidate == current:
            return
        reconciled, environment_updates = _reconcile_overlay_document(
            path,
            kind,
            candidate,
            existing_document=current,
        )
        _validate_overlay_candidate(path, kind, reconciled, subject, environment_updates)
        carry_pending(stored, subject, delivered=_ignore_migration_delivery)
        transaction.replace_text(render_declared_config(kind, reconciled))
    _write_overlay_environment(path, kind, environment_updates)


def _reconcile_overlay_document(
    path: Path,
    kind: ConfigKind,
    document: dict[str, Any],  # guard: loose-dict - Pydantic model_dump output
    *,
    existing_document: Mapping[str, object] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:  # guard: loose-dict - raw YAML config
    """Reconcile a typed save payload with raw reference-bearing YAML."""
    raw = existing_document if existing_document is not None else (_read_config_mapping(path) if path.exists() else {})
    references = find_environment_references(raw)
    environment = (
        read_environment_file(
            path.with_name(ConfigFileName.ENV),
            owner_only=kind in (ConfigKind.COMPANY, ConfigKind.PERSON),
        )
        if references
        else {}
    )
    reconciled, updates = reconcile_environment_references(raw, document, environment)
    if not isinstance(reconciled, dict):
        raise ValueError(f"Configuration document must be a mapping: {path}")
    return reconciled, updates


def _write_overlay_environment(path: Path, kind: ConfigKind, updates: Mapping[str, str]) -> None:
    """Apply placeholder-backed changes only to the owning sibling environment file."""
    if not updates:
        return
    if kind is ConfigKind.GLOBAL:
        with _global_environment_write(updates, path) as (transaction, creation_mode):
            replace_environment_values(transaction, updates, creation_mode=creation_mode)
        return
    creation_mode = company_environment_creation_mode() if kind is ConfigKind.COMPANY else None
    write_environment_values(path.with_name(ConfigFileName.ENV), updates, creation_mode=creation_mode)


def normalize_person_config_key(value: str) -> str:
    """Normalize a person name or username for tolerant config directory matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _person_config_keys(person: PersonEntry) -> set[str]:
    keys = {normalize_person_config_key(person.name)}
    if person.username:
        keys.add(normalize_person_config_key(person.username))
    if person.slug:
        keys.add(normalize_person_config_key(person.slug))
    return keys


def find_person_config_path(person: PersonEntry, people_dir: Path = PEOPLE_DIR) -> Path | None:
    """Find a person's config only in the registered slug folder."""
    if not person.slug:
        return None
    slug_path = people_dir / person.slug / ConfigFileName.OVERLAY
    return slug_path if slug_path.exists() else None


def resolve_declared_mail_account(
    person: PersonEntry,
    address: str,
    people_dir: Path = PEOPLE_DIR,
) -> DeclaredMailAccountResolution:
    """Resolve one declared account from its person's canonical overlay only."""
    registered_slug = person.slug
    if registered_slug is None:
        return RefusedDeclaredMailAccount(DeclaredMailAccountRefusal.MISSING_REGISTERED_SLUG)
    validate_slug(registered_slug)
    state_root = people_dir / registered_slug
    config_path = state_root / ConfigFileName.OVERLAY
    if not config_path.is_file():
        return RefusedDeclaredMailAccount(DeclaredMailAccountRefusal.CANONICAL_DOCUMENT_MISSING)
    raw_document: object = yaml.safe_load(config_path.read_text(encoding=_UTF8))
    persisted_claim = raw_document.get(_PERSON_SLUG_FIELD) if isinstance(raw_document, Mapping) else None
    if persisted_claim != registered_slug:
        return RefusedDeclaredMailAccount(DeclaredMailAccountRefusal.PERSISTED_CLAIM_MISMATCH)
    config = load_person_config(config_path)
    for account in config.mail_accounts:
        if account.address == address:
            return ResolvedDeclaredMailAccount(account=account, state_root=state_root)
    return RefusedDeclaredMailAccount(DeclaredMailAccountRefusal.ACCOUNT_NOT_DECLARED)


def load_person_config_for_entry(person: PersonEntry, people_dir: Path = PEOPLE_DIR) -> PersonConfig | None:
    """Load the per-person config for a global person entry when present."""
    person_config_path = find_person_config_path(person, people_dir)
    if person_config_path is None:
        return None
    if person.slug is None:
        raise ConfigLoadError(f"Person '{person.name}' has no registered slug", document=person_config_path)
    return load_person_config(person_config_path, registered_slug=person.slug)


def find_person_entry(
    *,
    people: list[PersonEntry],
    person_email: str | None = None,
    person_name: str | None = None,
    person_slug: str | None = None,
) -> PersonEntry | None:
    normalized_email = person_email.lower() if person_email else None
    normalized_name = normalize_person_config_key(person_name) if person_name else None
    for person in people:
        if person_slug and person.slug == person_slug:
            return person
        if normalized_email and person.email.lower() == normalized_email:
            return person
        if normalized_name and normalized_name in _person_config_keys(person):
            return person
    return None


def resolve_person_output_visibility_settings(
    *,
    person_email: str | None = None,
    person_name: str | None = None,
    person_slug: str | None = None,
    people: list[PersonEntry] | None = None,
    people_dir: Path = PEOPLE_DIR,
) -> OutputVisibilitySettings | None:
    """Resolve optional per-person output visibility settings for a recipient."""
    known_people = people if people is not None else load_global_config().people
    person = find_person_entry(
        people=known_people,
        person_email=person_email,
        person_name=person_name,
        person_slug=person_slug,
    )
    if person is None:
        return None
    person_config = load_person_config_for_entry(person, people_dir)
    if person_config is None:
        return None
    return person_config.settings.output_visibility


def load_app_config(workspace: Path) -> AppConfig:
    """Load composed app config for the given workspace.

    Determines workspace type (person vs. project) and loads the appropriate
    config layers. No fallback for unrecognized paths — returns global-only.
    """
    global_config = load_global_config()
    person_config: PersonConfig | None = None
    project_config: ProjectConfig | None = None
    company_config: CompanyConfig | None = None

    context = resolve_context_root(workspace)
    if context is not None:
        teleclaude_yml = context.path / ConfigFileName.OVERLAY
        if context.kind is ConfigKind.PERSON:
            person_config = load_person_config(teleclaude_yml)
        elif context.kind is ConfigKind.PROJECT:
            project_config = load_project_config(teleclaude_yml)

    # The company composes alongside the project — resolved from the project's
    # company membership, not from workspace type. Absent membership leaves it None.
    if project_config is not None and project_config.company:
        company_config = load_company_config_for_slug(project_config.company, COMPANIES_ROOT)
        if company_config is None:
            raise unregistered_referent(ReferentKind.COMPANY, project_config.company)
    if project_config is not None and project_config.person:
        person_owner = find_person_entry(people=global_config.people, person_slug=project_config.person)
        if person_owner is None:
            raise unregistered_referent(ReferentKind.PERSON, project_config.person)

    return AppConfig(
        global_=global_config,
        project=project_config,
        person=person_config,
        company=company_config,
    )


def validate_config(path: Path, level: str) -> BaseModel:
    """Dispatcher to validate configuration at a specific level."""
    if level == "project":
        return load_project_config(path)
    if level == "global":
        return load_global_config(path)
    if level == "person":
        return load_person_config(path)
    raise ValueError(f"Invalid config level: {level}")
