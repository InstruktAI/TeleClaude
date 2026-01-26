"""Project artifact syncing and file watching for TeleClaude."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from teleclaude.paths import REPO_ROOT


def sync_project_artifacts(project_root: Path) -> None:
    """Build snippet indexes and distribute artifacts.

    Args:
        project_root: Path to the project root directory.
    """
    env = os.environ.copy()
    commands = [
        [
            "uv",
            "run",
            "--quiet",
            "scripts/sync_resources.py",
            "--warn-only",
            "--project-root",
            str(project_root),
        ],
        [
            "uv",
            "run",
            "--quiet",
            "scripts/distribute.py",
            "--project-root",
            str(project_root),
            "--deploy",
        ],
    ]
    for cmd in commands:
        subprocess.run(cmd, cwd=project_root, check=True, env=env)


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


def _project_hash(project_root: Path) -> str:
    """Generate a short hash for the project path."""
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()
    return digest[:10]


def _install_launchd_watch(project_root: Path) -> None:
    """Install launchd file watcher on macOS."""
    label = f"ai.instrukt.teleclaude.docs.{_project_hash(project_root)}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    command = (
        f"cd {project_root} && "
        f"uv run --quiet scripts/sync_resources.py --warn-only --project-root {project_root} && "
        f"uv run --quiet scripts/distribute.py --project-root {project_root} --deploy"
    )
    watch_paths = [
        project_root / "AGENTS.md",
        project_root / ".agents",
        project_root / "agents",
        project_root / "docs" / "project",
        project_root / "docs" / "global",
        project_root / "teleclaude.yml",
    ]
    watch_entries = "\n".join(f"      <string>{path}</string>" for path in watch_paths)
    launchd_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    template_path = REPO_ROOT / "templates" / "ai.instrukt.teleclaude.docs-watch.plist"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        plist_content = (
            template.replace("{{LABEL}}", label)
            .replace("{{COMMAND}}", command)
            .replace("{{PATH}}", launchd_path)
            .replace("{{WATCH_PATHS}}", watch_entries)
        )
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
    <key>WatchPaths</key>
    <array>
{watch_entries}
    </array>
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


def _install_systemd_watch(project_root: Path) -> None:
    """Install systemd file watcher on Linux."""
    unit_id = f"teleclaude-docs-{_project_hash(project_root)}"
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / f"{unit_id}.service"
    path_path = unit_dir / f"{unit_id}.path"

    command = (
        f"cd {project_root} && "
        f"uv run --quiet scripts/sync_resources.py --warn-only --project-root {project_root} && "
        f"uv run --quiet scripts/distribute.py --project-root {project_root} --deploy"
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
