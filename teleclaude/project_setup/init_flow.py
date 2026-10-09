"""Project setup orchestration flow."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from teleclaude.capabilities import Capabilities, CapabilityName, resolve_capabilities
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.context_root import load_declared_config_kind
from teleclaude.config.declaration import render_declared_config, write_declared_config
from teleclaude.config.identity_schema import ProjectOwnerKind
from teleclaude.config.loader import registered_person_slugs, validate_tier_candidate
from teleclaude.config.migrations import Destination, MigrationTrigger, carry_pending, migrate_document, upcast
from teleclaude.config.migrations._registry import registered_subject
from teleclaude.config.project_home import HomeOwner, adoptable_home_owner, owning_home_owner
from teleclaude.config.schema import ConfigKind
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.reconciliation.home_convergence import project_targets
from teleclaude.core.reconciliation.template_installation import materialize_template_targets
from teleclaude.docs_index import ensure_project_config, get_project_slug
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import COMPANIES_ROOT, PEOPLE_DIR, ConfigFileName, is_platform_home
from teleclaude.project_manifest_runtime import project_adoption_lock, register_root
from teleclaude.project_root import resolve_project_root
from teleclaude.project_setup.git_repo import ensure_git_repo
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.skeleton import deploy_skeleton
from teleclaude.quality.scope import get_project_languages
from teleclaude.runtime.config import get_runtime_config, require_own_checkout
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.slug import derive_project_slug, normalize_slug, validate_slug
from teleclaude.utils import resolve_project_config_path

logger = get_logger(__name__)

_DOCS_DIRECTORY = "docs"
# `.agents/` is deliberately excluded: it is the local phase's delivery
# location, never an authored source, so its presence must never turn the
# `agents` capability on. See `teleclaude.agent_artifacts`.
_AGENT_DIRECTORIES = ("agents",)
_MAKEFILE_NAME = "Makefile"
_MARKDOWN_SUFFIX = ".md"
_FRONTMATTER_DELIMITER = "---"
_ENABLED_KEY = "enabled"
_KIND_KEY = "kind"
_DECLARATION_ENCODING = "utf-8"
_GIT_ENTRY = ".git"
_PROJECT_SLUG_KEY = "project_slug"
_PROJECT_NAME_KEY = "project_name"
_PROJECTS_FOLDER = "projects"
_UNREGISTERED_PROJECT_DECLARATION = "Project configuration is not registered: {path}"
_PROJECT_DECLARATION_NOT_MAPPING = "Project configuration must be a YAML mapping: {path}"
_GLOBAL_TIER_REFUSAL = "A global configuration cannot be adopted as a project."
_IDENTITY_CONFLICT = "Project identity '{identity}' is already held by {holding_root}."
_PROJECT_INITIALIZED_EVENT = "project_initialization_completed"
_CREATE_CLEANUP_EVENT = "project_creation_cleanup_skipped"
_NAME_TAKEN = "Project name '{identity}' is already taken by {holding_root}."
_NO_IDENTITY = "Cannot derive a project identity for {path}: neither its project slug, its project name nor its folder name yields one."
_DESTINATION_NOT_EMPTY = "Project destination is not empty: {path}"
_DESTINATION_NOT_DIRECTORY = "Project destination is not a folder: {path}"
_HOME_MISSING = "There is no {kind} home '{slug}' to create a project in."
_PLATFORM_PATH_INSIDE_HOME = "A platform project cannot live inside a home or the global home: {path}"
_DeclarationMutation = Callable[[dict[str, object]], bool]  # guard: loose-dict - raw YAML config


@dataclass(frozen=True)
class ProjectInitializationResult:
    """The declared identity and tier of one folder after a project act."""

    identity: str
    display_name: str
    kind: ConfigKind
    already_registered: bool


class ProjectInitializationTrigger(StrEnum):
    """The entry point that requested the project act."""

    CLI = "cli"
    DAEMON = "daemon"
    FOLD = "fold"


class ProjectOperation(StrEnum):
    """The project act a completed record describes."""

    CREATE = "create"
    ADOPT = "adopt"


@dataclass(frozen=True)
class PersonHomeDestination:
    """A new project in a person's own home."""

    person_slug: str


@dataclass(frozen=True)
class CompanyHomeDestination:
    """A new project in a company's home."""

    company_slug: str


@dataclass(frozen=True)
class PlatformPathDestination:
    """A new ownerless platform project at a folder outside every home."""

    path: Path


ProjectDestination = PersonHomeDestination | CompanyHomeDestination | PlatformPathDestination


class ProjectIdentityConflict(ValueError):
    """A different registered folder already owns the identity being adopted."""


def _ignore_migration_delivery(_destination: Destination) -> None:
    """Keep migration destinations outside project setup's return value."""


def _is_teleclaude_project(project_root: Path) -> bool:
    """Check if this is the TeleClaude project itself (not a user project)."""
    marker = project_root / "teleclaude" / "project_setup" / "init_flow.py"
    return marker.exists()


def _contains_file(directory: Path) -> bool:
    """Return whether a structural capability directory contains a file."""
    return directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))


def _contains_doc_snippet(project_root: Path) -> bool:
    """Detect authored snippet frontmatter without treating any docs folder as a subscription."""
    docs_root = project_root / _DOCS_DIRECTORY
    if not docs_root.is_dir():
        return False
    for path in docs_root.rglob(f"*{_MARKDOWN_SUFFIX}"):
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                if handle.readline().strip() == _FRONTMATTER_DELIMITER:
                    return True
        except OSError:
            continue
    return False


def _inferred_capabilities(project_root: Path) -> dict[CapabilityName, bool]:
    """Infer subscriptions from durable project structure at first adoption."""
    return {
        CapabilityName.CODE: (project_root / _MAKEFILE_NAME).is_file() or bool(get_project_languages(project_root)),
        CapabilityName.DOCS: _contains_doc_snippet(project_root),
        CapabilityName.AGENTS: any(_contains_file(project_root / name) for name in _AGENT_DIRECTORIES),
    }


def _update_project_declaration(project_root: Path, mutate: _DeclarationMutation) -> None:
    """Apply ``mutate`` to the registered project declaration, writing only when it reports a change.

    The current document is validated as ``ProjectConfig`` before it replaces
    the stored one, and migrations pending on the stored document are carried.
    """
    manifest_path = project_root / ConfigFileName.OVERLAY
    subject = registered_subject(manifest_path)
    if subject is None or subject.kind is not ConfigSubjectKind.PROJECT:
        raise ValueError(_UNREGISTERED_PROJECT_DECLARATION.format(path=manifest_path))
    with file_transaction(manifest_path) as transaction:
        stored = round_trip_yaml().load(transaction.read_text(encoding=_DECLARATION_ENCODING))
        if not isinstance(stored, dict):
            raise ValueError(_PROJECT_DECLARATION_NOT_MAPPING.format(path=manifest_path))
        raw = dict(upcast(stored, subject))
        if mutate(raw):
            validate_tier_candidate(manifest_path, ConfigKind.PROJECT, raw)
            carry_pending(stored, subject, delivered=_ignore_migration_delivery)
            transaction.replace_text(render_declared_config(ConfigKind.PROJECT, raw))


def _declare_inferred_capabilities(
    project_root: Path,
    undeclared_capabilities: frozenset[CapabilityName],
) -> Capabilities:
    """Materialize missing capability declarations while preserving explicit edits."""
    inferred = _inferred_capabilities(project_root)

    def declare(raw: dict[str, object]) -> bool:  # guard: loose-dict - raw YAML config
        changed = False
        for capability in undeclared_capabilities:
            if capability.value in raw:
                continue
            raw[capability.value] = {_ENABLED_KEY: inferred[capability]}
            changed = True
        return changed

    _update_project_declaration(project_root, declare)
    return resolve_capabilities(project_root)


def _ensure_project_slug(project_root: Path) -> None:
    """Ensure ``teleclaude.yml`` carries a valid ``project_slug`` entry.

    ``project_slug`` is the canonical machine identity used by the project
    catalog service, cross-project snippet resolution, and job subscription.
    When the config file already defines a valid slug we leave it alone; when
    absent, we derive one from ``project_name`` (or the directory name) and
    persist it via an in-place rewrite that preserves surrounding keys.

    ``ensure_project_config`` materializes a bare ``teleclaude.yml`` before
    initialization proceeds. Missing files and undecodable YAML raise
    :class:`RuntimeError` — ``project_slug`` is a hard init invariant, not an
    optional enhancement.
    """
    config_path = resolve_project_config_path(project_root)
    if not config_path.exists():
        raise RuntimeError(
            f"cannot write project_slug: {config_path} does not exist after configuration setup",
        )

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    try:
        raw = yaml_rt.load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot read {config_path} to write project_slug: {exc}") from exc
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("project_slug")
    if isinstance(existing, str) and existing.strip():
        try:
            validate_slug(existing.strip())
            return
        except ValueError:
            # Fall through and overwrite an invalid slug.
            pass

    seed = raw.get("project_name") if isinstance(raw.get("project_name"), str) else None
    slug = normalize_slug(seed or project_root.name)
    if not slug:
        raise RuntimeError(
            f"cannot derive a valid project_slug for {project_root}: "
            "neither project_name nor the directory name normalized to a usable slug",
        )

    raw["project_slug"] = slug
    write_declared_config(config_path, ConfigKind.PROJECT, raw)


def _identity_holder(identity: str, root: Path | None, *, include_in_transit: bool) -> Path | None:
    """Return the registered folder that already owns an identity, if any.

    ``root`` is the folder being adopted, which never conflicts with itself; creation passes
    ``None`` because no folder holds a name before it exists.
    """
    catalog = get_project_catalog_service()
    catalog.refresh()
    for entry in catalog.list_entries(include_in_transit=include_in_transit):
        if entry.identity == identity and entry.root != root:
            return entry.root

    return None


def _name_holder(name: str) -> Path | None:
    """Return the registered folder that holds a project name, including one whose declaration no longer loads.

    A registered project whose declaration is rejected on load, such as an in-home project naming another
    owner, drops out of the catalog's entries but keeps its registry path and its declared name. The name
    stays reserved: it is read from the raw declaration, so creation cannot hand it out a second time.
    """
    holding_root = _identity_holder(name, None, include_in_transit=True)
    if holding_root is not None:
        return holding_root
    _entries, unresolved_roots = get_project_catalog_service().list_entries_with_unresolved_roots()
    for root in unresolved_roots:
        try:
            held_identity = project_identity(root)
        except (OSError, ValueError, YAMLError):
            continue
        if held_identity == name:
            return root
    return None


def _declared_display_name(project_root: Path, kind: ConfigKind, identity: str) -> str:
    """Read the display name associated with a declared folder tier."""
    path = project_root / ConfigFileName.OVERLAY
    if not path.is_file():
        return identity
    document = round_trip_yaml().load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return identity
    name_field = "project_name" if kind is ConfigKind.PROJECT else "name"
    name = document.get(name_field)
    return name.strip() if isinstance(name, str) and name.strip() else identity


def _read_declaration(project_root: Path) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Read the folder's declaration as a raw mapping, empty when it declares nothing yet."""
    config_path = project_root / ConfigFileName.OVERLAY
    if not config_path.is_file():
        return {}
    document = round_trip_yaml().load(config_path.read_text(encoding=_DECLARATION_ENCODING))
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError(_PROJECT_DECLARATION_NOT_MAPPING.format(path=config_path))
    return dict(document)


def _declared_owner_slug(
    declaration: Mapping[str, object], owner_field: str
) -> str | None:  # guard: loose-dict - raw YAML config
    """Return a declared owner slug, or ``None`` when the field is absent or blank."""
    value = declaration.get(owner_field)
    return value.strip() if isinstance(value, str) and value.strip() else None


def project_identity(project_root: Path) -> str:
    """Return the identity a folder's declaration gives its project, read without validating ownership.

    Adoption decides and records a home's owner before any ownership-validating load, so it names
    the identity from the raw declaration.
    """
    declaration = _read_declaration(project_root)
    identity = derive_project_slug(declaration.get(_PROJECT_SLUG_KEY), declaration.get(_PROJECT_NAME_KEY), project_root)
    if identity is None:
        raise ValueError(_NO_IDENTITY.format(path=project_root))
    return identity


def _register_home_tier(
    project_root: Path,
    kind: ConfigKind,
    operation: ProjectOperation,
    trigger: ProjectInitializationTrigger,
) -> ProjectInitializationResult:
    """Record a person or company home as it is: a session home, not a project."""
    identity = project_root.name
    holding_root = _identity_holder(
        identity,
        project_root,
        include_in_transit=trigger is not ProjectInitializationTrigger.FOLD,
    )
    if holding_root is not None:
        raise ProjectIdentityConflict(_IDENTITY_CONFLICT.format(identity=identity, holding_root=holding_root))
    already_registered = not register_root(project_root=project_root)
    return _completed(
        project_root,
        ProjectInitializationResult(
            identity=identity,
            display_name=_declared_display_name(project_root, kind, identity),
            kind=kind,
            already_registered=already_registered,
        ),
        operation,
        trigger,
    )


def _completed(
    project_root: Path,
    result: ProjectInitializationResult,
    operation: ProjectOperation,
    trigger: ProjectInitializationTrigger,
) -> ProjectInitializationResult:
    """Record one finished project act and hand its result back."""
    logger.info(
        _PROJECT_INITIALIZED_EVENT,
        project_root=str(project_root),
        identity=result.identity,
        kind=result.kind.value,
        already_registered=result.already_registered,
        operation=operation.value,
        trigger=trigger.value,
    )
    return result


def _establish_repository_and_declaration(project_root: Path) -> frozenset[CapabilityName]:
    """Give the folder its repository and declaration; return the capability blocks it does not declare yet."""
    ensure_git_repo(project_root)
    # Establish the project configuration before the remaining setup steps.
    ensure_project_config(project_root)
    declaration = _read_declaration(project_root)
    return frozenset(capability for capability in CapabilityName if capability.value not in declaration)


def _record_home_owner(project_root: Path, home: HomeOwner | None) -> None:
    """Write the containing home's owner into the registered declaration when it names none."""
    if home is None:
        return

    def record(raw: dict[str, object]) -> bool:  # guard: loose-dict - raw YAML config
        if raw.get(home.kind.value) == home.slug:
            return False
        raw.update(home.declaration())
        return True

    _update_project_declaration(project_root, record)


def _converge_project_plumbing(project_root: Path) -> None:
    """Converge a registered root's plumbing and declared deployment output; the one deferred plumbing import of project setup."""
    from teleclaude.project_setup.plumbing import converge_root  # noqa: PLC0415 - avoids entrypoint preload.

    converge_root(project_root)


def _converge_registered_project(
    project_root: Path,
    registered_root: Path,
    undeclared_capabilities: frozenset[CapabilityName],
) -> None:
    """Run the stages every registered project goes through: migration, capabilities, templates, plumbing, slug."""
    is_mother = _is_teleclaude_project(project_root)
    migration_root = project_root if get_runtime_config().worktree_checkout is not None else registered_root
    require_own_checkout(migration_root)
    migrate_document(
        migration_root / ConfigFileName.OVERLAY,
        SubjectRef(ConfigSubjectKind.PROJECT),
        MigrationTrigger.REGISTRATION,
    )
    capabilities = _declare_inferred_capabilities(project_root, undeclared_capabilities)
    templates = project_targets(project_root, docs=capabilities.docs, help_desk=False)
    if templates:
        materialize_template_targets(templates, values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation
    if capabilities.docs:
        update_gitattributes(project_root)
    _converge_project_plumbing(project_root)
    if not is_mother and capabilities.code:
        deploy_skeleton(project_root)
    _ensure_project_slug(project_root)


def _registered_project_result(registered_root: Path, already_registered: bool) -> ProjectInitializationResult:
    """Describe a registered project from its declaration."""
    identity = get_project_slug(registered_root)
    return ProjectInitializationResult(
        identity=identity,
        display_name=_declared_display_name(registered_root, ConfigKind.PROJECT, identity),
        kind=ConfigKind.PROJECT,
        already_registered=already_registered,
    )


def adopt_project(
    project_root: Path,
    *,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
) -> ProjectInitializationResult:
    """Register the folder where it is, through its declared configuration tier.

    A project folder receives its repository, its owner and plumbing convergence
    before registration completes. Inside a person's or company's home the home's
    owner is recorded and a different declared owner is refused before anything is
    written; outside every home the declared owner stays. The global home's
    repository never holds a project, so a folder inside it gets one of its own.
    Person and company homes are registered in their declared tier without project
    setup. This operation asks nothing and is idempotent. It spawns no agent
    sessions and syncs no artifacts.

    A project subscribing ``docs`` receives its local baseline manifests when
    they are absent.

    Mother-aware: when invoked inside the TeleClaude repo itself, skeleton
    deployment is skipped — it only makes sense for downstream projects.

    AI-driven project analysis and quality-config assessment are explicit,
    separate acts started with ``telec sessions run --command
    /projects-analyze`` and ``telec sessions run --command
    /projects-assess-config`` — never a side effect of this function.
    """
    with project_adoption_lock():
        return _adopt_locked(project_root, trigger)


def _adopt_locked(project_root: Path, trigger: ProjectInitializationTrigger) -> ProjectInitializationResult:
    project_root = project_root.expanduser().resolve()
    config_path = project_root / ConfigFileName.OVERLAY
    kind = load_declared_config_kind(config_path) if config_path.is_file() else ConfigKind.PROJECT
    if kind is ConfigKind.GLOBAL:
        raise ValueError(_GLOBAL_TIER_REFUSAL)
    if kind in (ConfigKind.PERSON, ConfigKind.COMPANY):
        return _register_home_tier(project_root, kind, ProjectOperation.ADOPT, trigger)

    require_own_checkout(project_root)
    declaration = _read_declaration(project_root)
    home = adoptable_home_owner(
        project_root,
        company=_declared_owner_slug(declaration, ProjectOwnerKind.COMPANY.value),
        person=_declared_owner_slug(declaration, ProjectOwnerKind.PERSON.value),
        person_slugs=registered_person_slugs(),
    )
    registered_root = (
        resolve_project_root(project_root)
        if config_path.is_file() and (project_root / _GIT_ENTRY).exists()
        else project_root
    )
    identity = project_identity(registered_root)
    holding_root = _identity_holder(
        identity,
        registered_root,
        include_in_transit=trigger is not ProjectInitializationTrigger.FOLD,
    )
    if holding_root is not None:
        raise ProjectIdentityConflict(_IDENTITY_CONFLICT.format(identity=identity, holding_root=holding_root))

    undeclared_capabilities = _establish_repository_and_declaration(project_root)
    registered_root = resolve_project_root(project_root)
    already_registered = not register_root(project_root=registered_root)
    _record_home_owner(project_root, home)
    _converge_registered_project(project_root, registered_root, undeclared_capabilities)
    return _completed(
        registered_root,
        _registered_project_result(registered_root, already_registered),
        ProjectOperation.ADOPT,
        trigger,
    )


def _inside_platform_home(path: Path) -> bool:
    """Return whether a path is the global home or lies beneath it."""
    return is_platform_home(path) or any(is_platform_home(parent) for parent in path.parents)


def _destination_root(name: str, destination: ProjectDestination) -> tuple[Path, dict[str, str]]:
    """Resolve where a created project lives and the owner that place implies, refusing a place that cannot hold it."""
    if isinstance(destination, PlatformPathDestination):
        root = destination.path.expanduser().resolve()
        if owning_home_owner(root, registered_person_slugs()) is not None or _inside_platform_home(root):
            raise ValueError(_PLATFORM_PATH_INSIDE_HOME.format(path=root))
        return root, {}
    if isinstance(destination, PersonHomeDestination):
        kind, slug, homes_root = ProjectOwnerKind.PERSON, destination.person_slug, PEOPLE_DIR
    else:
        kind, slug, homes_root = ProjectOwnerKind.COMPANY, destination.company_slug, COMPANIES_ROOT
    root = homes_root.resolve() / slug / _PROJECTS_FOLDER / name
    home = owning_home_owner(root, registered_person_slugs())
    if home is None or home.kind is not kind or home.slug != slug or not (home.home / ConfigFileName.OVERLAY).is_file():
        raise ValueError(_HOME_MISSING.format(kind=kind.value, slug=slug))
    return root, home.declaration()


def _require_empty_destination(root: Path) -> None:
    """Refuse a destination that exists and holds anything."""
    if not root.exists():
        return
    if not root.is_dir():
        raise ValueError(_DESTINATION_NOT_DIRECTORY.format(path=root))
    if any(root.iterdir()):
        raise ValueError(_DESTINATION_NOT_EMPTY.format(path=root))


def _missing_ancestors(root: Path) -> list[Path]:
    """Return the folders on the way to ``root`` that do not exist yet, deepest first."""
    missing: list[Path] = []
    current = root
    while not current.exists() and current != current.parent:
        missing.append(current)
        current = current.parent
    return missing


def _remove_created(root: Path, created: list[Path], *, preexisted: bool) -> None:
    """Undo a failed creation before registration: remove only what creation made, never what was there."""
    if preexisted:
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    elif root.exists():
        shutil.rmtree(root)
    for directory in created:
        if directory == root:
            continue
        try:
            directory.rmdir()
        except OSError as exc:
            logger.info(_CREATE_CLEANUP_EVENT, path=str(directory), error=str(exc))


def create_project(
    name: str,
    destination: ProjectDestination,
    *,
    trigger: ProjectInitializationTrigger = ProjectInitializationTrigger.CLI,
) -> ProjectInitializationResult:
    """Make a new, empty project: its own repository, its owner, its name as identity, registered.

    Everything that can refuse refuses before anything is written: an invalid name, a name any
    registry entry already holds, a destination that cannot hold the project, and a destination
    that is not empty. The project declares no capability blocks, because capabilities come from
    content and an empty folder would fix them off for good; the first convergence after
    scaffolding infers them. Nothing is scaffolded or synced. A failure before
    registration removes only what creation made; after registration the project is genuine and
    stays for convergence to finish.
    """
    with project_adoption_lock():
        return _create_locked(name, destination, trigger)


def _create_locked(
    name: str,
    destination: ProjectDestination,
    trigger: ProjectInitializationTrigger,
) -> ProjectInitializationResult:
    validate_slug(name)
    holding_root = _name_holder(name)
    if holding_root is not None:
        raise ProjectIdentityConflict(_NAME_TAKEN.format(identity=name, holding_root=holding_root))
    root, owner = _destination_root(name, destination)
    _require_empty_destination(root)
    require_own_checkout(root)

    preexisted = root.exists()
    created = _missing_ancestors(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        ensure_git_repo(root, always_init=True)
        write_declared_config(
            root / ConfigFileName.OVERLAY,
            ConfigKind.PROJECT,
            {_PROJECT_SLUG_KEY: name, **owner},
        )
        registered_root = resolve_project_root(root)
    except Exception:
        _remove_created(root, created, preexisted=preexisted)
        raise

    register_root(project_root=registered_root)
    require_own_checkout(registered_root)
    migrate_document(
        registered_root / ConfigFileName.OVERLAY,
        SubjectRef(ConfigSubjectKind.PROJECT),
        MigrationTrigger.REGISTRATION,
    )
    _converge_project_plumbing(registered_root)
    return _completed(
        registered_root,
        ProjectInitializationResult(
            identity=get_project_slug(registered_root),
            display_name=_declared_display_name(registered_root, ConfigKind.PROJECT, name),
            kind=ConfigKind.PROJECT,
            already_registered=False,
        ),
        ProjectOperation.CREATE,
        trigger,
    )
