"""macOS launcher installation and permission-probe setup helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from teleclaude.runtime.binaries import resolve_tmux_binary


def is_macos() -> bool:
    """Return True when running on macOS."""
    return sys.platform == "darwin"


def install_launchers(project_root: Path, skip_build: bool = False) -> None:
    """Install launcher bundles into ``~/Applications`` on macOS.

    Idempotent: existing target bundles are replaced.
    """
    if not is_macos():
        return

    applications_dir = Path.home() / "Applications"
    applications_dir.mkdir(parents=True, exist_ok=True)

    if not skip_build:
        tmux_builder = project_root / "src" / "TmuxLauncher" / "build.sh"
        if tmux_builder.exists():
            build_result = subprocess.run(
                [str(tmux_builder)],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
                env=os.environ.copy(),
            )
            if build_result.returncode == 0:
                print("telec init: built TmuxLauncher.app")
            else:
                print("telec init: failed to build TmuxLauncher.app; using existing bundle")
    else:
        print("telec init: skipping launcher build; using committed bundles")

    launcher_apps = (
        "TmuxLauncher.app",
        "ClaudeLauncher.app",
        "GeminiLauncher.app",
        "CodexLauncher.app",
    )
    for app_name in launcher_apps:
        source_app = project_root / "bin" / app_name
        target_app = applications_dir / app_name
        if not source_app.exists():
            print(f"telec init: launcher not found, skipping: {source_app}")
            continue
        if target_app.exists():
            shutil.rmtree(target_app)
        shutil.copytree(source_app, target_app, symlinks=True)
        print(f"telec init: installed {app_name} to {target_app}")


def run_permissions_probe(project_root: Path) -> bool:
    """Run end-of-init permission probe on macOS via tmux launcher.

    Returns ``True`` when probe completed and no denials were detected.
    """
    _ = project_root
    if not is_macos():
        return True

    tmux_wrapper = Path(resolve_tmux_binary())
    if not tmux_wrapper.exists():
        print(f"telec init: tmux launcher missing; skipping permission probe ({tmux_wrapper})")
        return False

    print("")
    print("telec init: We are now going to test your new binaries for permissions access on your computer.")
    print("telec init: If macOS shows a permissions popup and you agree, please allow access.")
    print("telec init: This is essential, otherwise TeleClaude agents cannot access required local files.")

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
        command = f"python3 {probe_path} ; sleep 8"
        run_result = subprocess.run(
            [str(tmux_wrapper), "new-session", "-d", "-s", probe_session, command],
            check=False,
            capture_output=True,
            text=True,
        )
        if run_result.returncode != 0:
            print("telec init: permission probe could not start via tmux launcher")
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
            print("telec init: permission probe found denied paths.")
            print("telec init: Open System Settings > Privacy & Security > Full Disk Access and enable launcher apps.")
        else:
            print("telec init: permission probe passed for tested protected paths")
        return not denied
    finally:
        probe_path.unlink(missing_ok=True)
