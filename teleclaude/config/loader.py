"""Configuration file loading and validation."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from instrukt_ai_logging import get_logger
from pydantic import BaseModel
from ruamel.yaml import YAML

from teleclaude.config._environment import (
    company_environment_creation_mode,
    expand_environment_references,
    find_environment_references,
    read_environment_file,
    reconcile_environment_references,
    write_environment_values,
)
from teleclaude.config._file_io import file_transaction
from teleclaude.config._file_migrations import (
    migrate_global_file,
    move_person_invite_token,
    remove_person_notifications,
    remove_person_voice_channel_id,
    rename_person_output_visibility_web_value,
)
from teleclaude.config.advancement import advance_config
from teleclaude.config.context_root import load_declared_config_kind, resolve_context_root
from teleclaude.config.declaration import render_declared_config, write_declared_config
from teleclaude.config.jobs_migration import migrate_jobs_config
from teleclaude.config.person_claim import migrate_person_claim_for_target
from teleclaude.config.schema import (
    AppConfig,
    CompanyConfig,
    ConfigKind,
    GlobalConfig,
    MailAccount,
    OutputVisibilitySettings,
    PersonConfig,
    PersonEntry,
    ProjectConfig,
)
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, PEOPLE_DIR, ConfigFileName
from teleclaude.slug import validate_slug

logger = get_logger(__name__)
_PERSON_SLUG_FIELD = "slug"
_PERSON_CLAIM_MISMATCH = "Person config claim '{claim}' does not match save target '{target}'"
_UNRESOLVED_COMPANY_OWNER = "Project declares unresolved company owner: {owner}"
_UNRESOLVED_PERSON_OWNER = "Project declares unresolved person owner: {owner}"
_UTF8 = "utf-8"


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
    pre_validation: Callable[[], None] | None = None,
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

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config file %s: %s", path, e)
        raise ValueError(f"Failed to read config file {path}: {e}") from e

    if not raw:
        return model_class.model_validate(defaults)

    advance_config(path, kind, root)
    if pre_validation is not None:
        pre_validation()
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config file %s: %s", path, e)
        raise ValueError(f"Failed to read config file {path}: {e}") from e

    if kind is ConfigKind.GLOBAL:
        canonical_people_dir = (
            PEOPLE_DIR if path.expanduser().resolve() == GLOBAL_CONFIG_PATH.expanduser().resolve() else None
        )
        migrate_global_file(path, canonical_people_dir)
        raw = _read_config_mapping(path)
    if kind in (ConfigKind.GLOBAL, ConfigKind.PROJECT):
        migrate_jobs_config(path, kind)
        raw = _read_config_mapping(path)
    references = find_environment_references(raw)
    environment_path = path.with_name(ConfigFileName.ENV)
    local_environment = (
        read_environment_file(environment_path, owner_only=kind in (ConfigKind.COMPANY, ConfigKind.PERSON))
        if references
        else {}
    )
    expanded = expand_environment_references(raw, local_environment, config_path=path)
    try:
        model = model_class.model_validate(expanded)
    except Exception as exc:
        raise ValueError(f"Failed to validate config file {path}: {exc}") from exc
    return model


def _read_config_mapping(path: Path) -> object:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config file %s: %s", path, e)
        raise ValueError(f"Failed to read config file {path}: {e}") from e


def load_project_config(path: Path) -> ProjectConfig:
    """Load project-level configuration."""
    return load_config(path, ProjectConfig, ConfigKind.PROJECT, path.parent)


def load_declared_project_config(root: Path) -> ProjectConfig | None:
    """Load the project configuration for a root declaring `kind: project`.

    Returns `None` when `root` carries no configuration file, or carries one
    declaring a tier other than project. Raises `ValueError` for a malformed
    declaration, matching `load_project_config`'s existing contract.
    """
    marker = root / ConfigFileName.OVERLAY
    if not marker.is_file():
        return None
    if load_declared_config_kind(marker) is not ConfigKind.PROJECT:
        return None
    return load_project_config(marker)


def save_project_config(path: Path, config: ProjectConfig) -> None:
    """Save project config to disk using atomic write (temp + rename)."""
    data = config.model_dump(mode="json", exclude_defaults=True)
    _write_overlay_config(path, ConfigKind.PROJECT, data)


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
    with file_transaction(target) as transaction:
        existing: dict[str, Any] = {}  # guard: loose-dict - raw YAML config
        content = transaction.read_text()
        if content:
            yaml_rt = YAML()
            existing = yaml_rt.load(content) or {}
        overlay = _model_to_dict(config)
        merged = _deep_merge(existing, overlay)
        reconciled, environment_updates = _reconcile_overlay_document(target, ConfigKind.GLOBAL, merged)
        transaction.replace_text(render_declared_config(ConfigKind.GLOBAL, reconciled))
    _write_overlay_environment(target, ConfigKind.GLOBAL, environment_updates)
    logger.info("Saved global config to %s (merged, preserved %d existing keys)", target, len(existing))


def save_person_config(slug: str, config: PersonConfig) -> None:
    """Atomic write of per-person config keyed by slug. Creates directory if needed."""
    validate_slug(slug)
    if config.slug != slug:
        raise ValueError(_PERSON_CLAIM_MISMATCH.format(claim=config.slug, target=slug))
    person_dir = PEOPLE_DIR / slug
    person_dir.mkdir(parents=True, exist_ok=True)
    target = person_dir / ConfigFileName.OVERLAY
    data = _model_to_dict(config)
    _write_overlay_config(target, ConfigKind.PERSON, data)
    logger.info("Saved person config for %s to %s", slug, target)


def load_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global-level configuration."""
    if path is None:
        path = GLOBAL_CONFIG_PATH
    return load_config(path, GlobalConfig, ConfigKind.GLOBAL, path.parent)


def load_person_config(path: Path, *, registered_slug: str | None = None) -> PersonConfig:
    """Load per-person configuration."""
    default_fields = {_PERSON_SLUG_FIELD: registered_slug} if registered_slug is not None else None
    return load_config(
        path,
        PersonConfig,
        ConfigKind.PERSON,
        path.parent,
        default_fields=default_fields,
        pre_validation=_person_claim_pre_validation(path, registered_slug),
    )


def _person_claim_pre_validation(path: Path, registered_slug: str | None) -> Callable[[], None]:
    """Build the person-only transition that runs after generic tier advancement."""

    def migrate_person_claim() -> None:
        people: Iterable[PersonEntry] = load_global_config().people
        migrate_person_claim_for_target(path, people)
        remove_person_notifications(path)
        remove_person_voice_channel_id(path)
        rename_person_output_visibility_web_value(path)
        slug = registered_slug or next(
            (
                person.slug
                for person in people
                if person.slug and PEOPLE_DIR / person.slug / ConfigFileName.OVERLAY == path
            ),
            None,
        )
        if slug is not None:
            move_person_invite_token(path, slug)

    return migrate_person_claim


def load_company_config(path: Path) -> CompanyConfig:
    """Load company-tier configuration."""
    return load_config(path, CompanyConfig, ConfigKind.COMPANY, path.parent)


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
) -> None:
    """Persist one overlay while retaining its raw environment references."""
    reconciled, environment_updates = _reconcile_overlay_document(path, kind, document)
    write_declared_config(path, kind, reconciled)
    _write_overlay_environment(path, kind, environment_updates)


def _reconcile_overlay_document(
    path: Path,
    kind: ConfigKind,
    document: dict[str, Any],  # guard: loose-dict - Pydantic model_dump output
) -> tuple[dict[str, Any], dict[str, str]]:  # guard: loose-dict - raw YAML config
    """Reconcile a typed save payload with raw reference-bearing YAML."""
    raw = _read_config_mapping(path) if path.exists() else {}
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
    """Find a per-person config file by slug, falling back to legacy name/username keys.

    The slug-named folder is the canonical location; the legacy scan covers the
    transition window before a person's folder has been renamed to its slug.
    """
    if person.slug:
        slug_path = people_dir / person.slug / ConfigFileName.OVERLAY
        if slug_path.exists():
            return slug_path
    person_keys = _person_config_keys(person)
    for person_config_path in sorted(people_dir.glob(f"*/{ConfigFileName.OVERLAY}")):
        if normalize_person_config_key(person_config_path.parent.name) in person_keys:
            return person_config_path
    return None


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
        raise ValueError(f"Person '{person.name}' has no registered slug")
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
            raise ValueError(_UNRESOLVED_COMPANY_OWNER.format(owner=project_config.company))
    if project_config is not None and project_config.person:
        person_owner = find_person_entry(people=global_config.people, person_slug=project_config.person)
        if person_owner is None:
            raise ValueError(_UNRESOLVED_PERSON_OWNER.format(owner=project_config.person))

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
