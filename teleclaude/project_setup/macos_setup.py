"""macOS launcher installation and permission-probe setup helpers."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TypedDict

from teleclaude.paths import TELECLAUDE_HOME
from teleclaude.runtime.binaries import resolve_tmux_binary

_TMUX_SERVER_LABEL = "ai.instrukt.tmux-server"
_TMUX_SERVER_SWITCH = "--teleclaude-server"


class _TmuxServerPlist(TypedDict):
    Label: str
    ProgramArguments: list[str]
    WorkingDirectory: str
    RunAtLoad: bool
    KeepAlive: bool
    ThrottleInterval: int
    StandardOutPath: str
    StandardErrorPath: str


def is_macos() -> bool:
    """Return True when running on macOS."""
    return sys.platform == "darwin"


def install_launchers(project_root: Path) -> None:
    """Install launcher bundles into ``~/Applications`` on macOS.

    Idempotent: existing target bundles are replaced.
    """
    if not is_macos():
        return

    applications_dir = Path.home() / "Applications"
    applications_dir.mkdir(parents=True, exist_ok=True)

    launcher_apps = (
        "TmuxLauncher.app",
        "ClaudeLauncher.app",
        "GeminiLauncher.app",
        "CodexLauncher.app",
    )
    missing_apps = [
        project_root / "bin" / app_name for app_name in launcher_apps if not (project_root / "bin" / app_name).is_dir()
    ]
    if missing_apps:
        missing_names = ", ".join(app.name for app in missing_apps)
        raise FileNotFoundError(
            f"make install: launcher bundle(s) missing: {missing_names}; run 'make launchers' first"
        )

    for app_name in launcher_apps:
        source_app = project_root / "bin" / app_name
        target_app = applications_dir / app_name
        if target_app.exists():
            shutil.rmtree(target_app)
        shutil.copytree(source_app, target_app, symlinks=True)
        print(f"make install: installed {app_name} to {target_app}")


def _tmux_server_plist(tmux_wrapper: Path, teleclaude_home: Path) -> _TmuxServerPlist:
    return {
        "Label": _TMUX_SERVER_LABEL,
        "ProgramArguments": [str(tmux_wrapper), _TMUX_SERVER_SWITCH],
        "WorkingDirectory": str(teleclaude_home),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 2,
        "StandardOutPath": str(teleclaude_home / "logs" / "tmux-server.log"),
        "StandardErrorPath": str(teleclaude_home / "logs" / "tmux-server.error.log"),
    }


def install_tmux_server_service(
    *,
    home: Path | None = None,
    teleclaude_home: Path | None = None,
    launchctl: str = "/bin/launchctl",
) -> None:
    """Install the launchd-owned foreground tmux server on macOS."""
    if not is_macos():
        return

    resolved_home = home or Path.home()
    resolved_teleclaude_home = teleclaude_home or TELECLAUDE_HOME
    tmux_wrapper = resolved_home / "Applications" / "TmuxLauncher.app" / "Contents" / "MacOS" / "tmux-launcher"
    if not tmux_wrapper.is_file():
        raise FileNotFoundError(f"tmux launcher missing: {tmux_wrapper}")

    resolved_teleclaude_home.mkdir(parents=True, exist_ok=True)
    (resolved_teleclaude_home / "logs").mkdir(parents=True, exist_ok=True)
    plist_dir = resolved_home / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{_TMUX_SERVER_LABEL}.plist"
    plist_bytes = plistlib.dumps(
        _tmux_server_plist(tmux_wrapper, resolved_teleclaude_home),
        fmt=plistlib.FMT_XML,
        sort_keys=False,
    )
    changed = not plist_path.exists() or plist_path.read_bytes() != plist_bytes
    if changed:
        temp_path = plist_path.with_suffix(".plist.tmp")
        temp_path.write_bytes(plist_bytes)
        temp_path.replace(plist_path)

    domain = f"gui/{os.getuid()}"
    service_target = f"{domain}/{_TMUX_SERVER_LABEL}"
    status = subprocess.run(
        [launchctl, "print", service_target],
        capture_output=True,
        text=True,
        check=False,
    )
    if not changed and status.returncode == 0:
        print(f"make install: tmux server service already loaded ({plist_path})")
        return

    if status.returncode == 0:
        subprocess.run(
            [launchctl, "bootout", domain, str(plist_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    bootstrap = subprocess.run(
        [launchctl, "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.returncode != 0:
        detail = bootstrap.stderr.strip() or bootstrap.stdout.strip()
        raise RuntimeError(f"failed to load {_TMUX_SERVER_LABEL}: {detail}")
    print(f"make install: installed tmux server service at {plist_path}")


def run_permissions_probe(project_root: Path) -> bool:
    """Run end-of-init permission probe on macOS via tmux launcher.

    Returns ``True`` when probe completed and no denials were detected.
    """
    _ = project_root
    if not is_macos():
        return True

    tmux_wrapper = Path(resolve_tmux_binary())
    if not tmux_wrapper.exists():
        print(f"make install: tmux launcher missing; skipping permission probe ({tmux_wrapper})")
        return False

    print("")
    print("make install: We are now going to test your new binaries for permissions access on your computer.")
    print("make install: If macOS shows a permissions popup and you agree, please allow access.")
    print("make install: This is essential, otherwise TeleClaude agents cannot access required local files.")

    probe_script = """import os
home = os.path.expanduser('~')
paths = [
    ('~/Library/Messages/chat.db', os.path.expanduser('~/Library/Messages/chat.db')),
    ('~/Library/Safari/History.db', os.path.expanduser('~/Library/Safari/History.db')),
    ('~/Library/Mail', os.path.expanduser('~/Library/Mail')),
    ('~/Library/CloudStorage', os.path.expanduser('~/Library/CloudStorage')),
]
print('PERMISSIONS_PROBE_START')
for label, p in paths:
    print(f'PATH: {label}')
    try:
        st = os.stat(p)
        print(f'  stat: ok mode={oct(st.st_mode & 0o777)} size={st.st_size}')
    except Exception as exc:
        print(f'  stat: ERROR {type(exc).__name__}: {exc}')
        continue
    if os.path.isdir(p):
        try:
            sample = os.listdir(p)[:5]
            print(f'  listdir: ok sample={sample}')
        except Exception as exc:
            print(f'  listdir: ERROR {type(exc).__name__}: {exc}')
    else:
        try:
            with open(p, 'rb') as handle:
                handle.read(64)
            print('  read: ok bytes=64')
        except Exception as exc:
            print(f'  read: ERROR {type(exc).__name__}: {exc}')
print('PERMISSIONS_PROBE_DONE')
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp_file:
        tmp_file.write(probe_script)
        probe_path = Path(tmp_file.name)

    probe_session = "tc_perm_probe"
    subprocess.run(
        [str(tmux_wrapper), "kill-session", "-t", probe_session],
        check=False,
        capture_output=True,
        text=True,
    )

    denied = True
    try:
        command = f"{sys.executable} {probe_path} ; sleep 8"
        run_result = subprocess.run(
            [str(tmux_wrapper), "new-session", "-d", "-s", probe_session, command],
            check=False,
            capture_output=True,
            text=True,
        )
        if run_result.returncode != 0:
            print("make install: permission probe could not start via tmux launcher")
            return False

        time.sleep(2.0)
        capture_result = subprocess.run(
            [str(tmux_wrapper), "capture-pane", "-p", "-t", probe_session, "-S", "-220"],
            check=False,
            capture_output=True,
            text=True,
        )
        output = capture_result.stdout.strip()
        if output:
            print(output)

        denied = bool(re.search(r"Operation not permitted|PermissionError|denied", output))
        if denied:
            print("make install: permission probe found denied paths.")
            print(
                "make install: Open System Settings > Privacy & Security > Full Disk Access and enable launcher apps."
            )
        else:
            print("make install: permission probe passed for tested protected paths")
        return not denied
    finally:
        probe_path.unlink(missing_ok=True)
