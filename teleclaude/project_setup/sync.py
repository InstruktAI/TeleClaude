"""Project artifact syncing and file watching for TeleClaude."""

import os
import subprocess
import sys
from pathlib import Path

from teleclaude.paths import REPO_ROOT


def sync_project_artifacts(project_root: Path) -> None:
    """Build snippet indexes and distribute artifacts via ``telec sync``.

    Args:
        project_root: Path to the project root directory.
    """
    from teleclaude.sync import sync

    ok = sync(project_root, warn_only=True)
    if not ok:
        print("telec init: sync completed with warnings.")


def install_docs_watch(project_root: Path) -> None:
    """Install platform-specific file watcher for auto-rebuild.

    Args:
        project_root: Path to the project root directory.
    """
    if sys.platform == "darwin":
        _install_launchd_watch(project_root)
        return
    if sys.platform.startswith("linux"):
        _install_systemd_watch(project_root)
        return
    print("telec init: unsupported OS for auto-sync watcher.")


def _project_label(project_root: Path) -> str:
    """Generate a stable label from the project name."""
    name = project_root.name.strip() or "teleclaude"
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "teleclaude"


def _install_launchd_watch(project_root: Path) -> None:
    """Install launchd file watcher on macOS."""
    label = f"ai.instrukt.teleclaude.docs.{_project_label(project_root)}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    command = f"uv run --quiet --project {REPO_ROOT} -m teleclaude.cli.telec watch --project-root {project_root}"
    launchd_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    _remove_stale_launchd_plists(plist_path.parent, project_root)

    template_path = REPO_ROOT / "templates" / "ai.instrukt.teleclaude.docs-watch.plist"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        plist_content = (
            template.replace("{{LABEL}}", label)
            .replace("{{COMMAND}}", command)
            .replace("{{PATH}}", launchd_path)
            .replace("<key>WatchPaths</key>", "<!-- WatchPaths removed for telec watch -->")
            .replace("<array>\n{{WATCH_PATHS}}\n    </array>", "")
        )
        # Inject KeepAlive if missing
        if "<key>KeepAlive</key>" not in plist_content:
            plist_content = plist_content.replace("<dict>", "<dict>\n    <key>KeepAlive</key>\n    <true/>")
    else:
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>-lc</string>
      <string>{command}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>{launchd_path}</string>
    </dict>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
  </dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True)
    if subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=False).returncode != 0:
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)


def _remove_stale_launchd_plists(launchd_dir: Path, project_root: Path) -> None:
    """Remove stale TeleClaude docs watcher plists that reference this project."""
    if not launchd_dir.exists():
        return
    for plist in launchd_dir.glob("ai.instrukt.teleclaude.docs.*.plist"):
        if plist.name == f"ai.instrukt.teleclaude.docs.{_project_label(project_root)}.plist":
            continue
        try:
            content = plist.read_text(encoding="utf-8")
        except Exception:
            continue
        if str(project_root) not in content:
            continue
        try:
            plist.unlink()
        except Exception:
            continue


def _install_systemd_watch(project_root: Path) -> None:
    """Install systemd file watcher on Linux."""
    unit_id = f"teleclaude-docs-{_project_label(project_root)}"
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / f"{unit_id}.service"
    path_path = unit_dir / f"{unit_id}.path"

    command = (
        f"uv run --quiet --project {REPO_ROOT} -m teleclaude.cli.telec sync --warn-only --project-root {project_root}"
    )

    service_template_path = REPO_ROOT / "templates" / "teleclaude-docs-watch.service"
    path_template_path = REPO_ROOT / "templates" / "teleclaude-docs-watch.path"

    if service_template_path.exists():
        service_template = service_template_path.read_text(encoding="utf-8")
        service_content = service_template.replace("{{PROJECT_ROOT}}", str(project_root)).replace(
            "{{COMMAND}}", command
        )
    else:
        service_content = f"""[Unit]
Description=TeleClaude docs sync ({project_root})

[Service]
Type=oneshot
WorkingDirectory={project_root}
ExecStart=/bin/bash -lc '{command}'
"""

    if path_template_path.exists():
        path_template = path_template_path.read_text(encoding="utf-8")
        path_content = path_template.replace("{{PROJECT_ROOT}}", str(project_root)).replace("{{UNIT_ID}}", unit_id)
    else:
        path_content = f"""[Unit]
Description=TeleClaude docs watch ({project_root})

[Path]
PathModified={project_root}/AGENTS.md
PathModified={project_root}/.agents
PathModified={project_root}/agents
PathModified={project_root}/docs
PathModified={project_root}/agents/docs
PathModified={project_root}/teleclaude.yml
Unit={unit_id}.service

[Install]
WantedBy=default.target
"""

    service_path.write_text(service_content, encoding="utf-8")
    path_path.write_text(path_content, encoding="utf-8")

    if subprocess.run(["systemctl", "--user", "daemon-reload"], check=False).returncode != 0:
        print("telec init: systemd user services unavailable.")
        return
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{unit_id}.path"], check=False)
