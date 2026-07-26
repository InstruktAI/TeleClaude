from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.process

REPO_ROOT = Path(__file__).resolve().parents[2]
_SUBPROCESS_TIMEOUT_SECONDS = 10


def test_setup_frontend_runs_pnpm_through_corepack_without_a_global_shim(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    install_root = tmp_path / "install-root"
    frontend = install_root / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text(
        json.dumps({}),
        encoding="utf-8",
    )
    (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    corepack_log = tmp_path / "corepack.log"
    bare_pnpm_marker = tmp_path / "bare-pnpm-invoked"

    corepack = fake_bin / "corepack"
    corepack.write_text(
        (
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$COREPACK_LOG"\n'
            'if [ "$*" = "pnpm --version" ]; then\n'
            "    printf '11.10.0\\n'\n"
            "fi\n"
        ),
        encoding="utf-8",
    )
    corepack.chmod(0o755)

    pnpm = fake_bin / "pnpm"
    pnpm.write_text(
        '#!/bin/sh\ntouch "$BARE_PNPM_MARKER"\nexit 99\n',
        encoding="utf-8",
    )
    pnpm.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "BARE_PNPM_MARKER": str(bare_pnpm_marker),
            "COREPACK_LOG": str(corepack_log),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "TEST_INSTALL_ROOT": str(install_root),
        }
    )
    # Bash is the production interface for install.sh; no Python API can exercise its command dispatch.
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            (
                f'source "{REPO_ROOT / "bin/install.sh"}"; '
                'INSTALL_DIR="$TEST_INSTALL_ROOT"; '
                'LOG_FILE="$TEST_INSTALL_ROOT/install.log"; '
                "setup_frontend"
            ),
        ],
        capture_output=True,
        env=env,
        text=True,
        check=False,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr
    assert not bare_pnpm_marker.exists()
    assert corepack_log.read_text(encoding="utf-8") == snapshot
