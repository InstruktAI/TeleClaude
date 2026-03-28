"""Install OS-managed todo watcher services and persist their shared secret."""

from __future__ import annotations

import hashlib
import os
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

from teleclaude.paths import REPO_ROOT, TELECLAUDE_HOME

_WATCHER_SECRET_DIR = TELECLAUDE_HOME / "watcher-secrets"


def install_todo_watcher(project_root: Path) -> None:
    """Install the platform-specific todo watcher service for a project."""
    resolved_root = project_root.resolve()
    watcher_secret = _ensure_watcher_secret(resolved_root)

    if sys.platform == "darwin":
        _install_launchd_watch(resolved_root, watcher_secret)
        return
    if sys.platform.startswith("linux"):
        _install_systemd_watch(resolved_root, watcher_secret)
        return

    print("telec init: unsupported OS for todo watcher service.")


def get_watcher_secret(project_root: Path) -> str | None:
    """Read the persisted watcher secret for a project."""
    secret_path = _secret_path_for_project(project_root.resolve())
    if not secret_path.exists():
        return None
    return secret_path.read_text(encoding="utf-8").strip() or None


def _ensure_watcher_secret(project_root: Path) -> str:
    """Create a project-specific watcher secret when one does not exist."""
    existing_secret = get_watcher_secret(project_root)
    if existing_secret:
        return existing_secret

    watcher_secret = secrets.token_hex(32)
    secret_path = _secret_path_for_project(project_root)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(watcher_secret, encoding="utf-8")
    return watcher_secret


def _secret_path_for_project(project_root: Path) -> Path:
    """Build the on-disk secret path for a project root."""
    secret_id = hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()
    return _WATCHER_SECRET_DIR / f"{secret_id}.secret"


def _project_label(project_root: Path) -> str:
    """Generate a stable per-project service label."""
    resolved_root = project_root.resolve()
    name = resolved_root.name.strip() or "teleclaude"
    slug = "".join(character.lower() if character.isalnum() else "-" for character in name)
    slug = "-".join(part for part in slug.split("-") if part)
    label_root = slug or "teleclaude"
    suffix = hashlib.sha256(str(resolved_root).encode("utf-8")).hexdigest()[:12]
    return f"{label_root}-{suffix}"


def _watcher_command(project_root: Path) -> str:
    """Build the shell command that runs the todo watcher process."""
    quoted_repo_root = shlex.quote(str(REPO_ROOT))
    quoted_project_root = shlex.quote(str(project_root))
    return f"uv run --quiet --project {quoted_repo_root} -m teleclaude.cli.todo_watch {quoted_project_root}"


def _install_launchd_watch(project_root: Path, watcher_secret: str) -> None:
    """Install the macOS launchd agent for the todo watcher."""
    label = f"ai.instrukt.teleclaude.todo.{_project_label(project_root)}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    command = _watcher_command(project_root)
    launchd_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>WorkingDirectory</key>
    <string>{project_root}</string>
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
      <key>TELECLAUDE_WATCHER_SECRET</key>
      <string>{watcher_secret}</string>
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
    # launchctl has no Python API; shelling out is required to install user agents.
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=False)


def _install_systemd_watch(project_root: Path, watcher_secret: str) -> None:
    """Install the Linux systemd user service for the todo watcher."""
    unit_id = f"teleclaude-todo-{_project_label(project_root)}"
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / f"{unit_id}.service"

    command = _watcher_command(project_root)
    service_content = f"""[Unit]
Description=TeleClaude todo watcher ({project_root})

[Service]
Type=simple
WorkingDirectory={project_root}
Environment=PATH={os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
Environment=TELECLAUDE_WATCHER_SECRET={watcher_secret}
ExecStart={command}
Restart=on-failure

[Install]
WantedBy=default.target
"""
    service_path.write_text(service_content, encoding="utf-8")

    # systemctl has no Python API; shelling out is required to manage user services.
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{unit_id}.service"], check=False)


__all__ = ["get_watcher_secret", "install_todo_watcher"]
