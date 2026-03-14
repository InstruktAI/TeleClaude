"""Project setup orchestration flow."""

from __future__ import annotations

import io
import logging
import subprocess
import sys
from pathlib import Path

import yaml
from ruamel.yaml import YAML

from teleclaude.install.install_hooks import main as install_agent_hooks
from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.git_repo import ensure_git_repo, ensure_hooks_path
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.hooks import install_precommit_hook
from teleclaude.project_setup.macos_setup import install_launchers, is_macos, run_permissions_probe
from teleclaude.project_setup.sync import install_docs_watch, sync_project_artifacts

logger = logging.getLogger(__name__)

# Valid release channels.
_RELEASE_CHANNELS = ("alpha", "beta", "stable")


def _is_teleclaude_project(project_root: Path) -> bool:
    """Check if this is the TeleClaude project itself (not a user project)."""
    marker = project_root / "teleclaude" / "project_setup" / "init_flow.py"
    return marker.exists()


def _has_generated_snippets(project_root: Path) -> bool:
    """Check whether the project already has telec-init generated snippets."""
    from teleclaude.project_setup.enrichment import read_existing_snippets

    return bool(read_existing_snippets(project_root))


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


def _prompt_release_channel(project_root: Path) -> None:
    """Prompt for release-channel enrollment and persist to teleclaude.yml."""
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
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
        choice = input(
            f"Release channel ({'/'.join(_RELEASE_CHANNELS)}) [{current_channel}]: "
        ).strip().lower()
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
    except Exception as exc:
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


def _launch_enrichment(project_root: Path) -> None:
    """Launch the telec-init-analyze session for project enrichment."""
    print("\nStarting project analysis...")
    cmd = [
        sys.executable, "-m", "teleclaude.cli.telec",
        "sessions", "run",
        "--command", "/telec-init-analyze",
        "--project", str(project_root),
    ]
    try:
        result = subprocess.run(cmd, check=False, timeout=300, capture_output=True, text=True)
        if result.returncode == 0:
            print("Enrichment session started. Analysis will produce project doc snippets.")
        else:
            logger.warning("Enrichment session failed (rc=%d): %s", result.returncode, result.stderr.strip())
            print("Enrichment session could not be started. You can run it later with:")
            print(f"  telec sessions run --command /telec-init-analyze --project {project_root}")
    except subprocess.TimeoutExpired:
        logger.warning("Enrichment session timed out after 300s")
        print("Enrichment session timed out. You can retry with:")
        print(f"  telec sessions run --command /telec-init-analyze --project {project_root}")
    except OSError as exc:
        logger.warning("Could not launch enrichment session: %s", exc)
        print("Could not launch enrichment session. You can run it manually with:")
        print(f"  telec sessions run --command /telec-init-analyze --project {project_root}")


def _offer_enrichment(project_root: Path) -> None:
    """Detect first-init vs re-init and offer enrichment accordingly."""
    if not sys.stdin.isatty():
        return  # Non-interactive: skip enrichment prompt entirely.
    is_reinit = _has_generated_snippets(project_root)

    if is_reinit:
        if _prompt_yes_no("\nRefresh project analysis? (re-analyze codebase and update doc snippets)"):
            _launch_enrichment(project_root)
        else:
            print("Skipping enrichment refresh.")
    else:
        if _prompt_yes_no("\nRun project analysis? (generate doc snippets from your codebase)"):
            _launch_enrichment(project_root)
        else:
            print("Skipping enrichment. You can run it later with: telec init")


def init_project(project_root: Path) -> None:
    """Initialize a project for TeleClaude.

    Sets up agent hooks, git filters, pre-commit hooks, syncs artifacts, and
    installs watchers. Optionally runs AI-driven project analysis to generate
    doc snippets that make the codebase legible to AI.
    """
    install_agent_hooks()
    ensure_git_repo(project_root)
    ensure_hooks_path(project_root)
    setup_git_filters(project_root)
    update_gitattributes(project_root)
    install_precommit_hook(project_root)
    sync_project_artifacts(project_root)
    from teleclaude.project_setup.domain_seeds import seed_event_domains

    seed_event_domains(project_root)
    install_docs_watch(project_root)

    if is_macos():
        install_launchers(project_root)
        run_permissions_probe(project_root)

    # Bootstrap help desk workspace if running from the TeleClaude project
    if _is_teleclaude_project(project_root):
        from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk

        bootstrap_help_desk()

    # Release channel enrollment
    _prompt_release_channel(project_root)

    # Offer AI-driven project enrichment
    _offer_enrichment(project_root)

    print("telec init complete.")
