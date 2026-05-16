"""Project setup orchestration flow."""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML

from teleclaude.config import config
from teleclaude.git import Repo
from teleclaude.install.configure_agent_cli import main as configure_agent_cli
from teleclaude.project_manifest import register_root
from teleclaude.project_setup.domain_seeds import seed_event_domains
from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.git_repo import ensure_git_repo, ensure_hooks_path
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.hooks import ensure_precommit_safety_guards
from teleclaude.project_setup.macos_setup import install_launchers, is_macos, run_permissions_probe
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


def _prompt_yes_no(prompt: str, *, default: bool = True) -> bool:
    """Prompt user for a yes/no answer. Returns default when stdin is not a TTY."""
    suffix = " [Y/n] " if default else " [y/N] "
    if not sys.stdin.isatty():
        return default
    try:
        answer = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


_FRONTEND_CANDIDATES = ("frontend", "web", "client", "src")


def _detect_python(project_root: Path) -> bool:
    """Detect Python indicators at the project root."""
    if (project_root / "pyproject.toml").exists():
        return True
    if (project_root / "setup.py").exists():
        return True
    return any(project_root.glob("*.py"))


def _detect_typescript(project_root: Path) -> tuple[bool, str | None]:
    """Detect TypeScript indicators. Returns (found, frontend_root_relative)."""
    # Check root-level tsconfig.json
    if (project_root / "tsconfig.json").exists():
        return True, None

    # Check candidate frontend directories
    for candidate in _FRONTEND_CANDIDATES:
        candidate_dir = project_root / candidate
        if not candidate_dir.is_dir():
            continue
        has_ts = (candidate_dir / "tsconfig.json").exists()
        if not has_ts:
            pkg = candidate_dir / "package.json"
            if pkg.exists():
                try:
                    pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
                    deps = pkg_data.get("dependencies", {})
                    dev_deps = pkg_data.get("devDependencies", {})
                    has_ts = "typescript" in deps or "typescript" in dev_deps
                except (json.JSONDecodeError, OSError):
                    pass
        if has_ts:
            return True, candidate

    return False, None


def _detect_and_set_languages(project_root: Path) -> None:
    """Detect project languages and write to teleclaude.yml if changed.

    Non-interactive mode auto-writes detected values. Interactive mode
    prompts the user when detected languages differ from configured.
    """
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Could not read %s: %s — skipping language detection", config_path, exc)
        return
    if not isinstance(raw, dict):
        raw = {}

    existing_languages: list[str] = raw.get("languages", [])
    existing_frontend: str | None = raw.get("frontend_root")

    # Detect
    detected_languages: list[str] = []
    detected_frontend: str | None = None

    if _detect_python(project_root):
        detected_languages.append("python")

    ts_found, ts_root = _detect_typescript(project_root)
    if ts_found:
        detected_languages.append("typescript")
        detected_frontend = ts_root

    if not detected_languages:
        return

    # Check if anything changed
    if sorted(detected_languages) == sorted(existing_languages) and detected_frontend == existing_frontend:
        return

    # Interactive: prompt
    if sys.stdin.isatty():
        print(f"\nDetected languages: {', '.join(detected_languages)}")
        if detected_frontend:
            print(f"Frontend root: {detected_frontend}/")
        if existing_languages:
            print(f"Current config: {', '.join(existing_languages)}")
        if not _prompt_yes_no("Update language configuration?"):
            return

    # Write via ruamel.yaml to preserve comments
    _ryaml = YAML()
    _ryaml.preserve_quotes = True
    try:
        doc = _ryaml.load(config_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        doc = raw

    if not isinstance(doc, dict):
        doc = {}

    doc["languages"] = detected_languages
    if detected_frontend:
        doc["frontend_root"] = detected_frontend

    buf = io.StringIO()
    _ryaml.dump(doc, buf)
    config_path.write_text(buf.getvalue(), encoding="utf-8")
    logger.info("Updated languages: %s", detected_languages)


def _prompt_release_channel(project_root: Path) -> None:
    """Prompt for release-channel enrollment and persist to teleclaude.yml."""
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Could not read %s: %s — skipping release channel prompt", config_path, exc)
        return
    if not isinstance(raw, dict):
        raw = {}

    deployment = raw.get("deployment", {})
    if not isinstance(deployment, dict):
        deployment = {}
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

    # Persist only the deployment section, preserving comments and formatting.
    _ryaml = YAML()
    _ryaml.preserve_quotes = True
    try:
        doc = _ryaml.load(config_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Could not re-read %s for comment-preserving write: %s — using plain YAML", config_path, exc)
        doc = raw

    if not isinstance(doc, dict):
        doc = {}
    if "deployment" not in doc:
        doc["deployment"] = {}
    doc["deployment"]["channel"] = choice
    doc["deployment"]["pinned_minor"] = pinned_minor

    buf = io.StringIO()
    _ryaml.dump(doc, buf)
    config_path.write_text(buf.getvalue(), encoding="utf-8")
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

    Configures agent CLIs, git filters, pre-commit hooks, syncs artifacts,
    registers the project root, and prompts for release-channel enrollment.
    Idempotent and CI-safe; spawns no agent sessions.

    AI-driven project analysis and quality-config assessment live in
    ``teleclaude.project_setup.onboard_flow`` and are invoked via the
    ``telec projects {onboard,analyze,assess}`` commands.
    """
    configure_agent_cli()
    ensure_git_repo(project_root)
    ensure_hooks_path(project_root)
    setup_git_filters(project_root)
    update_gitattributes(project_root)
    ensure_precommit_safety_guards(project_root)
    # Sync runs first — ``ensure_project_config`` materializes a bare
    # ``teleclaude.yml`` when the project is fresh. Only after that can
    # ``_ensure_project_slug`` guarantee the canonical machine identity is
    # present before the project is registered with the catalog.
    sync_project_artifacts(project_root)
    _detect_and_set_languages(project_root)
    deploy_skeleton(project_root)
    _ensure_project_slug(project_root)
    register_root(project_root=project_root)
    seed_event_domains(project_root)

    if is_macos():
        install_launchers(project_root)
        run_permissions_probe(project_root)

    # Bootstrap help desk workspace if running from the TeleClaude project
    if _is_teleclaude_project(project_root):
        _bootstrap_help_desk(project_root)

    # Release channel enrollment
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
