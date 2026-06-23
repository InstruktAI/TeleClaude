"""Project setup orchestration flow."""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML

from teleclaude.config import config, config_path
from teleclaude.config.loader import _atomic_yaml_write
from teleclaude.git import Repo
from teleclaude.paths import GLOBAL_CONFIG_PATH
from teleclaude.project_manifest import register_root
from teleclaude.project_setup.domain_seeds import seed_event_domains
from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.git_repo import ensure_git_repo, ensure_hooks_path
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.hooks import install_precommit_hook
from teleclaude.project_setup.skeleton import deploy_skeleton
from teleclaude.project_setup.sync import sync_project_artifacts
from teleclaude.slug import normalize_slug, validate_slug

logger = get_logger(__name__)

# Valid release channels.
_RELEASE_CHANNELS = ("alpha", "beta", "stable")


def _is_teleclaude_project(project_root: Path) -> bool:
    """Check if this is the TeleClaude project itself (not a user project)."""
    marker = project_root / "teleclaude" / "project_setup" / "init_flow.py"
    return marker.exists()


def _write_deployment_block(machine_config_path: Path, channel: str, pinned_minor: str) -> None:
    """Persist the ``deployment`` block into the machine ``config.yml``, preserving comments.

    On a read or parse failure of an existing config, the error propagates and the
    file is left untouched — an unreadable config is never overwritten with a fresh
    deployment-only document, which would destroy the rest of the machine config.
    The write goes through the atomic config-layer writer after a successful
    round-trip load.
    """
    if machine_config_path.exists():
        ryaml = YAML()
        ryaml.preserve_quotes = True
        doc = ryaml.load(machine_config_path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError(f"Refusing to rewrite {machine_config_path}: existing content is not a YAML mapping")
    else:
        doc = {}
    if "deployment" not in doc or not isinstance(doc["deployment"], dict):
        doc["deployment"] = {}
    doc["deployment"]["channel"] = channel
    doc["deployment"]["pinned_minor"] = pinned_minor
    _atomic_yaml_write(machine_config_path, doc)


def migrate_legacy_deployment_channel(source_path: Path, machine_config_path: Path) -> bool:
    """Fold a legacy ``deployment:`` block from a ``teleclaude.yml`` into machine ``config.yml``.

    The release channel moved from the per-project config to the machine config, so
    a ``deployment:`` block in an existing project/global ``teleclaude.yml`` is now
    inert. Fold it into the machine config (the user's explicit channel wins over
    the seeded default) and strip the legacy key from the source so it never
    silently shadows the machine surface again. Returns whether a migration ran.
    """
    if not source_path.exists():
        return False
    ryaml = YAML()
    ryaml.preserve_quotes = True
    try:
        source_doc = ryaml.load(source_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Could not read %s for deployment migration: %s", source_path, exc)
        return False
    if not isinstance(source_doc, dict) or "deployment" not in source_doc:
        return False

    legacy = source_doc.get("deployment")
    if isinstance(legacy, dict):
        channel = str(legacy.get("channel", "alpha") or "alpha")
        pinned_minor = str(legacy.get("pinned_minor", "") or "")
        _write_deployment_block(machine_config_path, channel, pinned_minor)

    del source_doc["deployment"]
    _atomic_yaml_write(source_path, source_doc)
    logger.info("Migrated legacy deployment block from %s to %s", source_path, machine_config_path)
    return True


def migrate_legacy_deployment_sources(project_root: Path) -> bool:
    """Fold any legacy ``deployment:`` block from the global and project ``teleclaude.yml``
    into the machine ``config.yml``.

    Called on the daemon load path before the deployment readers
    (``config.deployment``) fire, so an existing install whose channel was set in a
    per-project ``teleclaude.yml`` is migrated to the machine surface rather than
    silently falling back to the seeded default. Returns whether any source migrated.
    """
    machine_config_path = config_path
    migrated = False
    for source in (GLOBAL_CONFIG_PATH, project_root / "teleclaude.yml"):
        if migrate_legacy_deployment_channel(source, machine_config_path):
            migrated = True
    return migrated


def _prompt_release_channel(project_root: Path) -> None:
    """Migrate any legacy block, then prompt for release-channel enrollment on the machine config."""
    machine_config_path = config_path
    migrate_legacy_deployment_channel(project_root / "teleclaude.yml", machine_config_path)

    current_channel = "alpha"
    current_pinned = ""
    if machine_config_path.exists():
        try:
            raw = yaml.safe_load(machine_config_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Could not read %s: %s — skipping release channel prompt", machine_config_path, exc)
            return
        if isinstance(raw, dict):
            deployment = raw.get("deployment", {})
            if isinstance(deployment, dict):
                current_channel = deployment.get("channel", "alpha")
                current_pinned = deployment.get("pinned_minor", "")

    if not sys.stdin.isatty():
        # Non-interactive: keep current settings.
        return

    print(f"\nRelease channel: currently '{current_channel}'")
    if current_channel == "stable" and current_pinned:
        print(f"  Pinned minor: {current_pinned}")

    try:
        choice = input(f"Release channel ({'/'.join(_RELEASE_CHANNELS)}) [{current_channel}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not choice:
        choice = current_channel
    if choice not in _RELEASE_CHANNELS:
        print(f"  Invalid channel '{choice}', keeping '{current_channel}'.")
        return

    pinned_minor = ""
    if choice == "stable":
        try:
            pinned_minor = input("  Pinned minor version (required for stable): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not pinned_minor:
            print("  Stable channel requires a pinned minor. Keeping current settings.")
            return

    _write_deployment_block(machine_config_path, choice, pinned_minor)
    print(f"  Release channel set to '{choice}'.")


def _ensure_project_slug(project_root: Path) -> None:
    """Ensure ``teleclaude.yml`` carries a valid ``project_slug`` entry.

    ``project_slug`` is the canonical machine identity used by the project
    catalog service, cross-project snippet resolution, and job subscription.
    When the config file already defines a valid slug we leave it alone; when
    absent, we derive one from ``project_name`` (or the directory name) and
    persist it via an in-place rewrite that preserves surrounding keys.

    This step runs **after** ``sync_project_artifacts`` so it can rely on
    ``ensure_project_config`` having already materialized a bare
    ``teleclaude.yml`` for fresh projects. Missing files and undecodable
    YAML raise :class:`RuntimeError` — ``project_slug`` is a hard init
    invariant, not an optional enhancement.
    """
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        raise RuntimeError(
            f"cannot write project_slug: {config_path} does not exist after sync",
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
    buffer = io.StringIO()
    yaml_rt.dump(raw, buffer)
    config_path.write_text(buffer.getvalue(), encoding="utf-8")


def init_project(project_root: Path) -> None:
    """Initialize a project for TeleClaude — plumbing only.

    Configures git filters and pre-commit hooks, syncs artifacts, registers
    the project root, and prompts for release-channel enrollment. Idempotent
    and CI-safe; spawns no agent sessions.

    Mother-aware: when invoked inside the TeleClaude repo itself, site-project
    bootstrap steps (skeleton deployment, release-channel prompt) are skipped
    — they only make sense for downstream projects.

    AI-driven project analysis and quality-config assessment live in
    ``teleclaude.project_setup.onboard_flow`` and are invoked via the
    ``telec projects {onboard,analyze,assess}`` commands.
    """
    is_mother = _is_teleclaude_project(project_root)

    ensure_git_repo(project_root)
    ensure_hooks_path(project_root)
    setup_git_filters(project_root)
    update_gitattributes(project_root)
    # Sync runs first — ``ensure_project_config`` materializes a bare
    # ``teleclaude.yml`` when the project is fresh. Only after that can
    # ``_ensure_project_slug`` guarantee the canonical machine identity is
    # present before the project is registered with the catalog.
    sync_project_artifacts(project_root)
    if not is_mother:
        deploy_skeleton(project_root)
    install_precommit_hook(project_root)
    _ensure_project_slug(project_root)
    register_root(project_root=project_root)
    seed_event_domains(project_root)

    # Bootstrap help desk workspace if running from the TeleClaude project
    if is_mother:
        _bootstrap_help_desk(project_root)
    else:
        # Release channel enrollment is a downstream-project concern.
        _prompt_release_channel(project_root)

    print("telec projects init complete.")


# ---------------------------------------------------------------------------
# Help desk bootstrap (inlined to avoid circular import with init_flow)
# ---------------------------------------------------------------------------


def _resolve_help_desk_dir() -> Path:
    """Resolve help desk directory from config or default sibling location."""
    configured = config.computer.help_desk_dir
    if configured:
        return Path(configured).expanduser().resolve()
    teleclaude_root = Path(__file__).resolve().parents[2]
    return teleclaude_root.parent / "help-desk"


def _bootstrap_help_desk(project_root: Path) -> None:
    """Scaffold the help desk workspace if it does not exist.

    Idempotent: skips if the directory already exists. Calls ``init_project``
    on the new directory, which is why this lives in init_flow rather than a
    separate module — the bootstrap is a sub-step of init.
    """
    help_desk_dir = _resolve_help_desk_dir()
    if help_desk_dir.exists():
        logger.info("help_desk_exists", path=str(help_desk_dir))
        return

    template_dir = project_root / "templates" / "help-desk"
    if not template_dir.exists():
        logger.warning("help_desk_template_missing", path=str(template_dir))
        return

    logger.info("help_desk_bootstrap_start", path=str(help_desk_dir))

    shutil.copytree(template_dir, help_desk_dir)

    try:
        repo = Repo.init(help_desk_dir)
        init_project(help_desk_dir)
        repo.git.add(".")
        repo.index.commit("Initial help desk scaffold")
    except Exception:
        shutil.rmtree(help_desk_dir, ignore_errors=True)
        raise

    logger.info("help_desk_bootstrap_complete", path=str(help_desk_dir))
