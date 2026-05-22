"""Behavioral coverage for the install script responsibility boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

_REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.timeout(20)


def _copy_checkout(tmp_path: Path) -> Path:
    project_root = tmp_path / "project_root"
    project_root.mkdir()
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".pytest_cache", ".ruff_cache")
    for file_name in ("Makefile", "pyproject.toml", "uv.lock", "config.sample.yml", ".env.sample", "mcp.json"):
        source = _REPO_ROOT / file_name
        if source.exists():
            shutil.copy2(source, project_root / file_name)
    for dir_name in ("bin", "teleclaude", "templates", "scripts"):
        shutil.copytree(_REPO_ROOT / dir_name, project_root / dir_name, ignore=ignore, symlinks=True)
    (project_root / "docs").mkdir()
    shutil.copytree(_REPO_ROOT / "docs" / "global", project_root / "docs" / "global", ignore=ignore, symlinks=True)
    return project_root


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _sandbox_env(tmp_path: Path) -> dict[str, str]:
    fake_home = tmp_path / "fakehome"
    stubs = tmp_path / "stubs"
    stub_log = tmp_path / "stub-log"
    fake_home.mkdir()
    (fake_home / ".local" / "bin").mkdir(parents=True)
    stubs.mkdir()
    stub_log.mkdir()

    real_python = sys.executable

    _write_executable(
        stubs / "git",
        """#!/usr/bin/env bash
set -euo pipefail
echo "git $*" >> "$STUB_LOG/git.log"
if [ "${1:-}" = "rev-parse" ]; then
  case "${2:-}" in
    --git-dir|--git-common-dir) echo ".git"; exit 0 ;;
  esac
fi
exit 0
""",
    )
    _write_executable(stubs / "uname", "#!/usr/bin/env bash\nprintf 'Linux\\n'\n")
    _write_executable(stubs / "sort", "#!/usr/bin/env bash\ncat\n")
    _write_executable(
        stubs / "python3.14",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "--version" ]; then
  echo "Python 3.14.0"
else
  exec "$REAL_PYTHON" "$@"
fi
""",
    )
    for name in ("python3.13", "python3.12", "python3.11", "python3"):
        (stubs / name).symlink_to(stubs / "python3.14")
    _write_executable(
        stubs / "node",
        """#!/usr/bin/env bash
set -euo pipefail
echo "node $*" >> "$STUB_LOG/node.log"
if [ "${1:-}" = "--version" ]; then
  echo "v20.0.0"
fi
""",
    )
    _write_executable(
        stubs / "npm",
        """#!/usr/bin/env bash
set -euo pipefail
echo "npm $*" >> "$STUB_LOG/npm.log"
if [ "${1:-}" = "--version" ]; then
  echo "10.0.0"
fi
""",
    )
    _write_executable(
        stubs / "tmux",
        """#!/usr/bin/env bash
set -euo pipefail
echo "tmux $*" >> "$STUB_LOG/tmux.log"
if [ "${1:-}" = "-V" ]; then
  echo "tmux 3.4"
fi
""",
    )
    for name in (
        "jq",
        "rg",
        "ffmpeg",
        "socat",
        "glow",
        "claude",
        "brew",
        "apt-get",
        "dnf",
        "pacman",
        "snap",
        "launchctl",
        "systemctl",
        "sleep",
    ):
        version_clause = 'if [ "${1:-}" = "--version" ]; then echo "claude 1.0.0"; fi' if name == "claude" else ""
        _write_executable(
            stubs / name,
            f"""#!/usr/bin/env bash
set -euo pipefail
echo "{name} $*" >> "$STUB_LOG/{name}.log"
{version_clause}
exit 0
""",
        )
    _write_executable(
        stubs / "sudo",
        """#!/usr/bin/env bash
set -euo pipefail
echo "sudo $*" >> "$STUB_LOG/sudo.log"
if [ "${1:-}" = "tee" ]; then
  cat > /dev/null
fi
exit 0
""",
    )
    _write_executable(
        stubs / "uv",
        """#!/usr/bin/env bash
set -euo pipefail
echo "uv $*" >> "$STUB_LOG/uv.log"
if [ "${1:-}" = "sync" ]; then
  mkdir -p .venv/bin
  cat > .venv/bin/python <<PY
#!/usr/bin/env bash
exec "$REAL_PYTHON" "\\$@"
PY
  chmod +x .venv/bin/python
  touch .venv/bin/activate
fi
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(fake_home),
            "PATH": f"{stubs}:{fake_home / '.local' / 'bin'}:{env['PATH']}",
            "REAL_PYTHON": real_python,
            "STUB_LOG": str(stub_log),
            "TELECLAUDE_HOME": str(fake_home / ".teleclaude"),
            "USER": "teleclaude-test",
        }
    )
    return env


def _inventory(root: Path) -> list[tuple[str, str, int | str]]:
    if not root.exists():
        return []
    entries: list[tuple[str, str, int | str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append(("symlink", rel, os.readlink(path)))
        elif path.is_file():
            entries.append(("file", rel, path.stat().st_size))
        elif path.is_dir():
            entries.append(("dir", rel, 0))
    return entries


def _redact_inventory(
    inventory: dict[str, list[tuple[str, str, int | str]]], tmp_path: Path
) -> dict[str, list[tuple[str, str, int | str]]]:
    redacted: dict[str, list[tuple[str, str, int | str]]] = {}
    for key, entries in inventory.items():
        redacted_entries = []
        for kind, rel, value in entries:
            if kind == "file":
                value = "file"
            if isinstance(value, str):
                value = value.replace(str(tmp_path), "TMP")
            redacted_entries.append((kind, rel, value))
        redacted[key] = redacted_entries
    return redacted


def _run_make_install(project_root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "install"],
        cwd=project_root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_make_install_no_prompt_on_closed_stdin(tmp_path: Path) -> None:
    project_root = _copy_checkout(tmp_path)
    env = _sandbox_env(tmp_path)

    process = _run_make_install(project_root, env)

    assert process.returncode == 0


def test_install_sh_does_not_source_bin_init_sh() -> None:
    assert not (_REPO_ROOT / "bin" / "init.sh").exists()


def test_install_sh_invokes_provision_logs_non_interactive(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _copy_checkout(tmp_path)
    stub_log = tmp_path / "provision-argv.txt"
    provision_script = project_root / "bin" / "provision-logs.sh"
    _write_executable(
        provision_script,
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> {stub_log}
""",
    )

    process = subprocess.run(
        ["bash", "-c", "source bin/install.sh; CI_MODE=false; provision_logs"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert process.returncode == 0
    assert stub_log.read_text(encoding="utf-8").splitlines() == snapshot


def test_make_install_idempotent_second_run(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = _copy_checkout(tmp_path)
    env = _sandbox_env(tmp_path)
    fake_home = Path(env["HOME"])

    first = _run_make_install(project_root, env)
    first_inventory = _redact_inventory(
        {
            "home": _inventory(fake_home),
            "project_venv": _inventory(project_root / ".venv"),
        },
        tmp_path,
    )
    second = _run_make_install(project_root, env)
    second_inventory = _redact_inventory(
        {
            "home": _inventory(fake_home),
            "project_venv": _inventory(project_root / ".venv"),
        },
        tmp_path,
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert first_inventory == second_inventory
    assert {"first": first_inventory, "second": second_inventory} == snapshot
