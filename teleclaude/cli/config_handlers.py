"""Shared config read/write/validate layer for interactive config UI.

Provides operations for user-facing configs:
- Global: ~/.teleclaude/teleclaude.yml
- Per-person: ~/.teleclaude/people/{name}/teleclaude.yml

Both the interactive menu and onboarding wizard consume this layer.
"""

from __future__ import annotations

import dataclasses
import fcntl
import importlib
import os
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

import teleclaude.config as _tc_config_module
from teleclaude.config.invitations import load_invitations, save_invitations
from teleclaude.config.loader import (
    _atomic_yaml_write,
    find_person_config_path,
    load_global_config,
    load_person_config,
)
from teleclaude.config.loader import save_global_config as save_global_config
from teleclaude.config.loader import save_person_config as save_person_config
from teleclaude.config.schema import CredsConfig, GlobalConfig, PersonConfig, PersonEntry
from teleclaude.paths import GLOBAL_CONFIG_PATH, INVITATIONS_PATH, PROJECT_ENV_PATH, TELECLAUDE_HOME, ConfigFileName

logger = get_logger(__name__)

_PEOPLE_DIR = TELECLAUDE_HOME / "people"


# --- Data classes ---


@dataclass
class ConfigArea:
    """A discoverable config section for the interactive menu."""

    name: str  # e.g. "adapters.telegram"
    label: str  # e.g. "Telegram"
    category: Literal["adapter", "people", "notifications", "environment"]  # e.g. "adapter"
    configured: bool
    model_class: type[BaseModel] | None


@dataclass
class EnvVarInfo:
    """Metadata for a required environment variable."""

    name: str
    adapter: str
    description: str
    example: str


@dataclass
class EnvVarStatus:
    """Environment variable presence status."""

    info: EnvVarInfo
    is_set: bool


@dataclass
class ValidationResult:
    """Result of validating one config area."""

    area: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# --- Adapter env var registry ---

_ADAPTER_ENV_VARS: dict[str, list[EnvVarInfo]] = {
    "system": [
        EnvVarInfo(
            "TELECLAUDE_LOG_LEVEL",
            "system",
            "Daemon log level (DEBUG, INFO, WARNING, ERROR)",
            "INFO",
        ),
    ],
    "telegram": [
        EnvVarInfo(
            "TELEGRAM_BOT_TOKEN",
            "telegram",
            "Telegram Bot API token",
            "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        ),
    ],
    "discord": [
        EnvVarInfo(
            "DISCORD_BOT_TOKEN",
            "discord",
            "Discord Bot Token",
            "MTA...",
        ),
        EnvVarInfo(
            "DISCORD_GUILD_ID",
            "discord",
            "Discord Server (Guild) ID",
            "123456789012345678",
        ),
    ],
    "ai": [
        EnvVarInfo(
            "ANTHROPIC_API_KEY",
            "ai",
            "Anthropic API key (summarizer)",
            "sk-ant-api03-...",
        ),
        EnvVarInfo(
            "OPENAI_API_KEY",
            "ai",
            "OpenAI API key (summarizer fallback, Whisper STT, TTS)",
            "sk-proj-...",
        ),
        EnvVarInfo(
            "GOOGLE_API_KEY",
            "ai",
            "Google Gemini API key (summarizer fallback)",
            "AIza...",
        ),
        EnvVarInfo(
            "SUMMARIZER_LLM_BASE_URL",
            "ai",
            "Local OpenAI-compatible summarizer endpoint (e.g. LM Studio)",
            "http://localhost:1234/v1",
        ),
        EnvVarInfo(
            "SUMMARIZER_LLM_MODEL",
            "ai",
            "Local summarizer model id loaded in the local server",
            "qwen3.5-0.8b",
        ),
    ],
    "voice": [
        EnvVarInfo(
            "ELEVENLABS_API_KEY",
            "voice",
            "ElevenLabs API key (text-to-speech)",
            "sk_...",
        ),
    ],
    "redis": [
        EnvVarInfo(
            "REDIS_URL",
            "redis",
            "Redis connection URL (multi-computer transport)",
            "redis://localhost:6379",
        ),
        EnvVarInfo(
            "REDIS_PASSWORD",
            "redis",
            "Redis password (multi-computer transport)",
            "your-redis-password",
        ),
    ],
    "whatsapp": [
        EnvVarInfo(
            "WHATSAPP_PHONE_NUMBER_ID",
            "whatsapp",
            "Business phone number ID from Meta",
            "123456789012345",
        ),
        EnvVarInfo(
            "WHATSAPP_ACCESS_TOKEN",
            "whatsapp",
            "System user token (long-lived)",
            "EAAx...",
        ),
        EnvVarInfo(
            "WHATSAPP_WEBHOOK_SECRET",
            "whatsapp",
            "App secret for webhook signature verification",
            "abc123...",
        ),
        EnvVarInfo(
            "WHATSAPP_VERIFY_TOKEN",
            "whatsapp",
            "Random string for webhook challenge-response",
            "my-verify-token",
        ),
        EnvVarInfo(
            "WHATSAPP_TEMPLATE_NAME",
            "whatsapp",
            "Template name for 24h window boundary messages",
            "hello_world",
        ),
        EnvVarInfo(
            "WHATSAPP_TEMPLATE_LANGUAGE",
            "whatsapp",
            "Template language code",
            "en_US",
        ),
        EnvVarInfo(
            "WHATSAPP_BUSINESS_NUMBER",
            "whatsapp",
            "Business phone number for invite deep links",
            "+1234567890",
        ),
    ],
    "email": [
        EnvVarInfo("EMAIL_FROM", "email", "Sender identity (Name <addr>)", "Some Name <app@doma.in>"),
        EnvVarInfo("EMAIL_REPLYTO", "email", "Reply-To header", "noreply <no-reply@doma.in>"),
        EnvVarInfo("SMTP_USERNAME", "email", "SMTP relay username", "1234abcd@smtp-brevo.com"),
        EnvVarInfo("SMTP_KEY", "email", "SMTP relay key/password", "xsmtpsib-..."),
        EnvVarInfo("SMTP_RELAY", "email", "SMTP relay host:port", "smtp-relay.brevo.com:587"),
    ],
    "backup": [
        EnvVarInfo("AWS_ACCESS_KEY_ID", "backup", "S3 access key id", "AKIA..."),
        EnvVarInfo("AWS_SECRET_ACCESS_KEY", "backup", "S3 secret access key", "..."),
        EnvVarInfo("AWS_S3_HOST", "backup", "S3 endpoint host", "s3.eu-central-1.amazonaws.com"),
        EnvVarInfo("AWS_S3_REGION", "backup", "S3 region", "eu-central-1"),
        EnvVarInfo("AWS_S3_BUCKET", "backup", "S3 bucket name", "my-teleclaude-backups"),
        EnvVarInfo("TELECLAUDE_BACKUP_PREFIX", "backup", "Key prefix for backups", "teleclaude/"),
    ],
    "firecrawl": [
        EnvVarInfo("FIRECRAWL_API_KEY", "firecrawl", "Firecrawl API key (web scraping)", "fc-..."),
    ],
}


# --- Reading ---


def get_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global config from ~/.teleclaude/teleclaude.yml."""
    return load_global_config(path or GLOBAL_CONFIG_PATH)


def get_person_config(slug: str) -> PersonConfig:
    """Load per-person config from ~/.teleclaude/people/{slug}/teleclaude.yml."""
    person_path = _PEOPLE_DIR / slug / ConfigFileName.OVERLAY
    return load_person_config(person_path)


def list_people(config: GlobalConfig | None = None) -> list[PersonEntry]:
    """Return all people from global config."""
    if config is None:
        config = get_global_config()
    return list(config.people)


def list_person_dirs() -> list[str]:
    """Scan ~/.teleclaude/people/ for person directories."""
    if not _PEOPLE_DIR.exists():
        return []
    return sorted(d.name for d in _PEOPLE_DIR.iterdir() if d.is_dir() and (d / ConfigFileName.OVERLAY).exists())


# --- Writing (atomic) ---
#
# The global/person config writers and their YAML helpers live in
# teleclaude.config.loader (the config domain). They are re-exported above so
# every existing importer of config_handlers is unaffected.


def save_machine_config(config: _tc_config_module.TeleclaudeConfig, path: Path | None = None) -> None:
    """Atomic write of machine configuration (config.yml)."""
    target = path or _tc_config_module.config_path
    data = dataclasses.asdict(config)
    if "default_agent" in data:
        default_agent = data.pop("default_agent")
        if "agents" not in data or not isinstance(data["agents"], dict):
            data["agents"] = {}
        data["agents"]["default"] = default_agent
    _atomic_yaml_write(target, data)
    logger.info("Saved machine config to %s", target)


def save_raw_machine_config(
    raw_config: dict[str, Any],  # guard: loose-dict - on-disk YAML config tree
    path: Path | None = None,
) -> None:
    """Atomic write of the raw config.yml tree as-is (sparse; defaults not materialized)."""
    target = path or _tc_config_module.config_path
    _atomic_yaml_write(target, raw_config)
    logger.info("Saved machine config to %s", target)


def add_person(entry: PersonEntry) -> None:
    """Add person to global people list and create their slug-keyed directory."""
    config = get_global_config()

    if not entry.slug:
        raise ValueError(f"Person '{entry.name}' must have a slug before being added")
    if any(p.slug == entry.slug for p in config.people):
        raise ValueError(f"Person with slug '{entry.slug}' already exists")

    config.people.append(entry)
    save_global_config(config)

    person_config = PersonConfig()
    save_person_config(entry.slug, person_config)
    logger.info("Added person '%s' (slug '%s') with role '%s'", entry.name, entry.slug, entry.role)


def rename_person(old_name: str, new_name: str) -> None:
    """Update a person's display name. The slug and workspace folder are immutable."""
    config = get_global_config()
    for person in config.people:
        if person.name == old_name:
            person.name = new_name
            save_global_config(config)
            logger.info("Renamed person display name from '%s' to '%s'", old_name, new_name)
            return


def remove_person(slug: str, delete_directory: bool = False) -> None:
    """Remove person from global list by slug. Optionally remove their config directory."""
    config = get_global_config()
    original_count = len(config.people)
    config.people = [p for p in config.people if p.slug != slug]

    if len(config.people) == original_count:
        raise ValueError(f"Person with slug '{slug}' not found")

    save_global_config(config)

    if delete_directory:
        person_dir = _PEOPLE_DIR / slug
        if person_dir.exists():
            shutil.rmtree(person_dir)
            logger.info("Removed person directory for slug '%s'", slug)

    logger.info("Removed person with slug '%s' from global config", slug)


_migration_done = False


def _migrate_invitations_if_needed() -> None:
    """Perform one-shot migration of invite tokens from per-person configs to the invitations store."""
    global _migration_done
    if _migration_done:
        return

    if not INVITATIONS_PATH.exists():
        logger.info("Invitations store does not exist. Migrating tokens from person configs.")
        invitations: dict[str, str] = {}
        person_dirs = list_person_dirs()
        yaml_loader = YAML()
        for name in person_dirs:
            person_path = _PEOPLE_DIR / name / ConfigFileName.OVERLAY
            if not person_path.exists():
                continue
            try:
                with open(person_path, encoding="utf-8") as f:
                    raw_data = yaml_loader.load(f) or {}
                if isinstance(raw_data, dict) and "invite_token" in raw_data:
                    token = raw_data["invite_token"]
                    if token and isinstance(token, str):
                        invitations[token] = name

                    person_config = get_person_config(name)
                    if person_config.model_extra is not None and "invite_token" in person_config.model_extra:
                        person_config.model_extra.pop("invite_token")
                    save_person_config(name, person_config)
            except (OSError, ValueError, YAMLError) as e:
                logger.warning("Failed to migrate invite_token for person '%s': %s", name, e)
        save_invitations(invitations)
    _migration_done = True


def generate_invite_token() -> str:
    """Generate a new invite token with format inv_{16_hex_chars}."""
    return f"inv_{secrets.token_hex(8)}"


def set_invite_token(slug: str) -> str:
    """Generate and persist a new invite token for the person slug. Returns the token."""
    _migrate_invitations_if_needed()
    token = generate_invite_token()

    invitations = load_invitations()
    # Remove any existing tokens mapped to this person
    for t, holder in list(invitations.items()):
        if holder == slug:
            del invitations[t]

    invitations[token] = slug
    save_invitations(invitations)

    # Also clean up any lingering invite_token from per-person config model_extra
    try:
        person_config = get_person_config(slug)
        if person_config.model_extra is not None and "invite_token" in person_config.model_extra:
            person_config.model_extra.pop("invite_token")
            save_person_config(slug, person_config)
    except (OSError, ValueError) as e:
        logger.warning("Failed to clean up invite_token in per-person config for '%s': %s", slug, e)

    logger.info("Set invite token for slug '%s'", slug)
    return token


def find_person_by_invite_token(token: str) -> tuple[str, PersonConfig] | None:
    """Find a person by their invite token using the O(1) invitations store. Returns (person_slug, config) or None."""
    _migrate_invitations_if_needed()
    invitations = load_invitations()
    if token in invitations:
        person_slug = invitations[token]
        try:
            person_config = get_person_config(person_slug)
            return (person_slug, person_config)
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Failed to load config for slug '%s': %s", person_slug, e)
            return None
    return None


# --- Validation ---


def _is_env_var_required(info: EnvVarInfo, app_config: Any | None) -> bool:
    """Whether this env var is required by the currently enabled adapters/services.

    Returns True only when the corresponding adapter/service has an active enable
    flag in config.yml. Groups without a config-level enable flag (`backup`,
    `firecrawl`, `system`, and cloud summarizer API keys) are treated as opt-in:
    their absence is silently OK because the runtime falls through.
    """
    group = info.adapter
    if group == "redis":
        # Redis env vars are optional: an unset REDIS_URL falls back to the
        # redis://localhost:6379 default in DEFAULT_CONFIG, and auth-less local
        # Redis needs no REDIS_PASSWORD. Reachability is enforced at the /ready
        # start boundary, not by env-var presence.
        return False
    if app_config is None:
        return False
    if group == "telegram":
        return bool(getattr(app_config.telegram, "enabled", False))
    if group == "discord":
        return bool(getattr(app_config.discord, "enabled", False))
    if group == "whatsapp":
        return bool(getattr(app_config.whatsapp, "enabled", False))
    if group == "email":
        email_cfg = getattr(app_config, "email", None)
        return bool(getattr(email_cfg, "enabled", False)) if email_cfg else False
    if group == "voice":
        # ELEVENLABS_API_KEY required only when ElevenLabs is an enabled TTS or STT service.
        for section_attr in ("tts", "stt"):
            section = getattr(app_config, section_attr, None)
            if not section or not getattr(section, "enabled", False):
                continue
            services = getattr(section, "services", None) or {}
            elevenlabs = services.get("elevenlabs")
            if elevenlabs and getattr(elevenlabs, "enabled", False):
                return True
        return False
    if group == "ai":
        # Local summarizer vars are gated by summarizer.local.enabled.
        # Cloud provider keys (ANTHROPIC/OPENAI/GOOGLE) are optional fallbacks —
        # the summarizer skips a provider silently when its key is absent.
        if info.name in ("SUMMARIZER_LLM_BASE_URL", "SUMMARIZER_LLM_MODEL"):
            summarizer = getattr(app_config, "summarizer", None)
            local = getattr(summarizer, "local", None) if summarizer else None
            return bool(local and getattr(local, "enabled", False))
        return False
    return False


def validate_all() -> list[ValidationResult]:
    """Run full-system validation: schema + cross-reference + env vars."""
    results: list[ValidationResult] = []

    # Validate global config (people, subscriptions, env_allow_list)
    try:
        config = get_global_config()
        results.append(ValidationResult(area="global", passed=True))
    except (ValueError, ValidationError) as e:
        results.append(
            ValidationResult(
                area="global",
                passed=False,
                errors=[str(e)],
                suggestions=["Check ~/.teleclaude/teleclaude.yml for syntax errors"],
            )
        )
        return results

    # Validate the runtime app config (~/.teleclaude/config.yml: adapters,
    # summarizer, agents, etc.). Import-time validation raises on schema errors;
    # we capture them as a result rather than letting them crash the validator.
    app_config: Any | None = None
    try:
        importlib.reload(_tc_config_module)
        app_config = _tc_config_module.config
        results.append(ValidationResult(area=ConfigFileName.MACHINE, passed=True))
    except Exception as e:
        results.append(
            ValidationResult(
                area=ConfigFileName.MACHINE,
                passed=False,
                errors=[str(e)],
                suggestions=["Check ~/.teleclaude/config.yml for schema errors"],
            )
        )

    # Validate each person config. Resolve the on-disk path by slug (the canonical
    # person-overlay location, people/{slug}/teleclaude.yml), with the resolver's
    # legacy name/username fallback for folders not yet renamed.
    for person in config.people:
        person_path = find_person_config_path(person, _PEOPLE_DIR)
        if person_path is None:
            expected_path = _PEOPLE_DIR / (person.slug or person.name) / ConfigFileName.OVERLAY
            results.append(
                ValidationResult(
                    area=f"person:{person.name}",
                    passed=False,
                    errors=[f"Config file missing: {expected_path}"],
                    suggestions=[f"Run: telec config to create config for {person.name}"],
                )
            )
            continue
        try:
            load_person_config(person_path)
            results.append(ValidationResult(area=f"person:{person.name}", passed=True))
        except (ValueError, ValidationError) as e:
            results.append(
                ValidationResult(
                    area=f"person:{person.name}",
                    passed=False,
                    errors=[str(e)],
                    suggestions=[f"Check {person_path} for errors"],
                )
            )

    # Validate environment variables — filtered by adapter enablement so
    # disabled adapters (whatsapp, email when off) don't false-positive.
    env_status = check_env_vars()
    missing = [s for s in env_status if not s.is_set and _is_env_var_required(s.info, app_config)]
    if missing:
        results.append(
            ValidationResult(
                area="environment",
                passed=False,
                errors=[f"Missing: {s.info.name} ({s.info.description})" for s in missing],
                suggestions=[f"Set {s.info.name}={s.info.example}" for s in missing],
            )
        )
    elif env_status:
        results.append(ValidationResult(area="environment", passed=True))

    return results


# --- Environment ---


def get_adapter_env_vars(adapter_name: str) -> list[EnvVarInfo]:
    """Return registered env vars for a specific adapter, regardless of usage."""
    return _ADAPTER_ENV_VARS.get(adapter_name, [])


def get_all_env_vars() -> dict[str, list[EnvVarInfo]]:
    """Return all registered env vars, grouped by service."""
    return dict(_ADAPTER_ENV_VARS)


def get_required_env_vars() -> dict[str, list[EnvVarInfo]]:
    """Return all registered env vars. Alias for get_all_env_vars."""
    return get_all_env_vars()


def check_env_vars() -> list[EnvVarStatus]:
    """Check which required env vars are set."""
    all_vars = get_required_env_vars()
    results: list[EnvVarStatus] = []
    for vars_list in all_vars.values():
        for info in vars_list:
            results.append(EnvVarStatus(info=info, is_set=bool(os.environ.get(info.name))))
    return results


def resolve_env_file_path(env_path: Path | None = None) -> Path:
    """Resolve the target env file path for config writes."""
    if env_path is not None:
        return env_path.expanduser()
    return PROJECT_ENV_PATH


def set_env_var(name: str, value: str, env_path: Path | None = None) -> Path:
    """Set or update an env var in the resolved env file and os.environ."""
    if not name or any(char in name for char in "\r\n="):
        raise ValueError("Invalid env var name")
    if any(char in value for char in "\r\n"):
        raise ValueError("Env var value cannot contain newlines")

    target = resolve_env_file_path(env_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    lock_path = target.with_suffix(".lock")
    tmp_path = target.with_suffix(".tmp")

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass

        try:
            lines: list[str] = []
            found = False
            if target.exists():
                lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
                for index, line in enumerate(lines):
                    stripped = line.lstrip()
                    if stripped.startswith(f"export {name}="):
                        lines[index] = f"export {name}={value}\n"
                        found = True
                        break
                    if stripped.startswith(f"{name}="):
                        lines[index] = f"{name}={value}\n"
                        found = True
                        break

            if not found:
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] = f"{lines[-1]}\n"
                lines.append(f"{name}={value}\n")

            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write("".join(lines))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass

    os.environ[name] = value
    logger.info("Updated env var %s in %s", name, target)
    return target


# --- Schema discovery ---


def _get_adapter_names() -> list[str]:
    """Discover adapter names from CredsConfig fields."""
    names: list[str] = []
    for field_name, field_info in CredsConfig.model_fields.items():
        if field_info.annotation is not None:
            names.append(field_name)
    return sorted(names)


def discover_config_areas() -> list[ConfigArea]:
    """Inspect schema models to find available config areas.

    Returns areas for: adapters (from CredsConfig), people, notifications, environment.
    """
    areas: list[ConfigArea] = []

    try:
        config = get_global_config()
    except (ValueError, ValidationError):
        config = GlobalConfig()

    # Adapter areas from CredsConfig fields
    for adapter_name in _get_adapter_names():
        configured = False
        for person in config.people:
            try:
                pc = get_person_config(person.name)
                if getattr(pc.creds, adapter_name, None) is not None:
                    configured = True
                    break
            except (ValueError, ValidationError):
                continue

        field_info = CredsConfig.model_fields[adapter_name]
        model_class = field_info.annotation
        # Unwrap Optional
        if hasattr(model_class, "__args__"):
            model_class = next(
                (a for a in model_class.__args__ if a is not type(None)),
                model_class,
            )

        areas.append(
            ConfigArea(
                name=f"adapters.{adapter_name}",
                label=adapter_name.capitalize(),
                category="adapter",
                configured=configured,
                model_class=model_class,
            )
        )

    # People area
    areas.append(
        ConfigArea(
            name="people",
            label="People",
            category="people",
            configured=len(config.people) > 0,
            model_class=PersonEntry,
        )
    )

    # Notifications area
    has_notifications = False
    for person in config.people:
        try:
            pc = get_person_config(person.name)
            if pc.subscriptions:
                has_notifications = True
                break
        except (ValueError, ValidationError):
            continue

    areas.append(
        ConfigArea(
            name="notifications",
            label="Notifications",
            category="notifications",
            configured=has_notifications,
            model_class=PersonConfig,
        )
    )

    # Environment area
    env_status = check_env_vars()
    all_set = all(s.is_set for s in env_status) if env_status else True
    areas.append(
        ConfigArea(
            name="environment",
            label="Environment",
            category="environment",
            configured=all_set,
            model_class=None,
        )
    )

    return areas
