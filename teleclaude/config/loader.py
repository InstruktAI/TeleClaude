"""Configuration file loading and validation."""

import fcntl
import os
import stat
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from instrukt_ai_logging import get_logger
from pydantic import BaseModel
from ruamel.yaml import YAML

from teleclaude.config.schema import (
    AppConfig,
    CompanyConfig,
    GlobalConfig,
    OutputVisibilitySettings,
    PersonConfig,
    PersonEntry,
    ProjectConfig,
)
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, PEOPLE_DIR
from teleclaude.slug import validate_slug
from teleclaude.utils import expand_env_vars

logger = get_logger(__name__)


def _warn_unknown_keys(model: BaseModel, path: str, config_path: Path) -> None:
    """Recursively warn about unknown keys in a model and its nested models."""
    if hasattr(model, "model_extra") and model.model_extra:
        logger.warning("Unknown keys in %s at %s: %s", path, config_path, list(model.model_extra.keys()))

    # Check nested BaseModel instances
    for field_name, field_value in model.__dict__.items():
        if isinstance(field_value, BaseModel):
            _warn_unknown_keys(field_value, f"{path}.{field_name}", config_path)
        elif isinstance(field_value, dict):
            # Check dict values for nested BaseModels
            for key, value in field_value.items():
                if isinstance(value, BaseModel):
                    _warn_unknown_keys(value, f"{path}.{field_name}.{key}", config_path)
        elif isinstance(field_value, list):
            # Check list items for nested BaseModels
            for idx, item in enumerate(field_value):
                if isinstance(item, BaseModel):
                    _warn_unknown_keys(item, f"{path}.{field_name}[{idx}]", config_path)


def load_config[T: BaseModel](path: Path, model_class: type[T]) -> T:
    """Load YAML config from ``path`` and validate it with ``model_class``.

    Args:
        path: Path to a configuration YAML file.
        model_class: The Pydantic model class to use for validation.

    Returns:
        The validated configuration model.
    """
    if not path.exists():
        return model_class()

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config file %s: %s", path, e)
        raise ValueError(f"Failed to read config file {path}: {e}") from e

    expanded = expand_env_vars(raw)
    model = model_class.model_validate(expanded)
    _warn_unknown_keys(model, "root", path)
    return model


def load_project_config(path: Path) -> ProjectConfig:
    """Load project-level configuration."""
    return load_config(path, ProjectConfig)


def save_project_config(path: Path, config: ProjectConfig) -> None:
    """Save project config to disk using atomic write (temp + rename)."""
    data = config.model_dump(mode="json", exclude_defaults=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _represent_enum(representer: Any, data: Enum) -> Any:
    """Serialize any Enum (incl. StrEnum) as its underlying value for YAML."""
    return representer.represent_data(data.value)


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:  # guard: loose-dict - YAML serialization boundary
    """Atomic YAML write using tmp file + os.replace.

    Preserves existing formatting when possible by using ruamel.yaml
    round-trip mode. Falls back to fresh write if file doesn't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    tmp_path = path.with_suffix(".tmp")

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.default_flow_style = False
    yaml_rt.representer.add_multi_representer(Enum, _represent_enum)

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml_rt.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass


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
    existing: dict[str, Any] = {}  # guard: loose-dict - raw YAML config
    if target.exists():
        yaml_rt = YAML()
        with open(target, encoding="utf-8") as f:
            existing = yaml_rt.load(f) or {}
    overlay = _model_to_dict(config)
    merged = _deep_merge(existing, overlay)
    _atomic_yaml_write(target, merged)
    logger.info("Saved global config to %s (merged, preserved %d existing keys)", target, len(existing))


def save_person_config(slug: str, config: PersonConfig) -> None:
    """Atomic write of per-person config keyed by slug. Creates directory if needed."""
    person_dir = PEOPLE_DIR / slug
    person_dir.mkdir(parents=True, exist_ok=True)
    target = person_dir / "teleclaude.yml"
    data = _model_to_dict(config)
    _atomic_yaml_write(target, data)
    logger.info("Saved person config for %s to %s", slug, target)


def load_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global-level configuration."""
    if path is None:
        path = GLOBAL_CONFIG_PATH
    return load_config(path, GlobalConfig)


def load_person_config(path: Path) -> PersonConfig:
    """Load per-person configuration."""
    return load_config(path, PersonConfig)


def load_company_config(path: Path) -> CompanyConfig:
    """Load company-tier configuration."""
    return load_config(path, CompanyConfig)


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
    _atomic_yaml_write(company_dir / "teleclaude.yml", _model_to_dict(config))
    logger.info("Saved company config for %s", slug)


def list_company_configs(companies_root: Path | None = None) -> list[tuple[str, CompanyConfig]]:
    """List folder-discovered companies as ``(slug, CompanyConfig)`` pairs, sorted by slug."""
    root = companies_root if companies_root is not None else COMPANIES_ROOT
    if not root.exists():
        return []
    pairs: list[tuple[str, CompanyConfig]] = []
    for config_path in sorted(root.glob("*/teleclaude.yml")):
        pairs.append((config_path.parent.name, load_company_config(config_path)))
    return pairs


def find_company_config_path(slug: str, companies_root: Path | None = None) -> Path | None:
    """Find a company's ``teleclaude.yml`` by slug-named folder under ``COMPANIES_ROOT``.

    Folder-discovery only: the slug is the company id and the folder name. No
    registry file — the ``COMPANIES_ROOT`` tree is the registry. Mirrors the
    per-person tier's discovery.
    """
    config_path = _company_dir(slug, companies_root) / "teleclaude.yml"
    return config_path if config_path.exists() else None


def load_company_config_for_slug(slug: str, companies_root: Path | None = None) -> CompanyConfig | None:
    """Load the company config for a slug when its folder is present."""
    company_config_path = find_company_config_path(slug, companies_root)
    if company_config_path is None:
        return None
    return load_company_config(company_config_path)


class CompanyCredentialsError(Exception):
    """Raised when a company ``.env`` exists but cannot be read safely.

    A missing ``.env`` is not an error — it means "no credentials". This error is
    reserved for the loud-failure cases: a world/group-readable file (secret
    exposure) or an unreadable file (the secret cannot be resolved). Failures are
    explicit rather than silently returning empty credentials.
    """


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
    env_path = _company_dir(slug, companies_root) / ".env"
    if not env_path.exists():
        return {}
    file_mode = env_path.stat().st_mode
    if file_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CompanyCredentialsError(
            f"Company '{slug}' .env is group/world-accessible ({stat.filemode(file_mode)}); "
            f"expected owner-only 0600. Refusing to load exposed credentials: {env_path}"
        )
    if not os.access(env_path, os.R_OK):
        raise CompanyCredentialsError(f"Company '{slug}' .env is not readable: {env_path}")
    return {key: value for key, value in dotenv_values(env_path).items() if value is not None}


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
        slug_path = people_dir / person.slug / "teleclaude.yml"
        if slug_path.exists():
            return slug_path
    person_keys = _person_config_keys(person)
    for person_config_path in sorted(people_dir.glob("*/teleclaude.yml")):
        if normalize_person_config_key(person_config_path.parent.name) in person_keys:
            return person_config_path
    return None


def load_person_config_for_entry(person: PersonEntry, people_dir: Path = PEOPLE_DIR) -> PersonConfig | None:
    """Load the per-person config for a global person entry when present."""
    person_config_path = find_person_config_path(person, people_dir)
    if person_config_path is None:
        return None
    return load_person_config(person_config_path)


def _find_person_entry(
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
    person = _find_person_entry(
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


def _is_person_workspace(workspace: Path) -> bool:
    """Check if workspace is a person directory under <base>/.teleclaude/people/."""
    return workspace.parent.name == "people" and workspace.parent.parent.name == ".teleclaude"


def load_app_config(workspace: Path) -> AppConfig:
    """Load composed app config for the given workspace.

    Determines workspace type (person vs. project) and loads the appropriate
    config layers. No fallback for unrecognized paths — returns global-only.
    """
    global_config = load_global_config()
    person_config: PersonConfig | None = None
    project_config: ProjectConfig | None = None
    company_config: CompanyConfig | None = None

    if _is_person_workspace(workspace):
        teleclaude_yml = workspace / "teleclaude.yml"
        if teleclaude_yml.exists():
            person_config = load_person_config(teleclaude_yml)
    else:
        teleclaude_yml = workspace / "teleclaude.yml"
        if teleclaude_yml.exists():
            project_config = load_project_config(teleclaude_yml)

    # The company composes alongside the project — resolved from the project's
    # company membership, not from workspace type. Absent membership leaves it None.
    if project_config is not None and project_config.company:
        company_config = load_company_config_for_slug(project_config.company, COMPANIES_ROOT)
        if company_config is None:
            # The project declares a company that does not resolve — surface the
            # misconfiguration; the company layer stays None (no other company leaks).
            logger.warning("project_company_unresolved", company=project_config.company)

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
