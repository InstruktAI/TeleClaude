"""Characterization tests for teleclaude.paths."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from teleclaude import paths


def test_repo_root_is_derived_from_module_location() -> None:
    assert paths.REPO_ROOT == Path(paths.__file__).resolve().parents[1]


def test_home_relative_paths_share_expected_bases() -> None:
    assert paths.TELECLAUDE_HOME == Path(os.environ["TELECLAUDE_HOME"])
    assert paths.STATE_DIR == paths.TELECLAUDE_HOME / "state"
    assert paths.GLOBAL_SNIPPETS_DIR == paths.TELECLAUDE_HOME / "docs"
    assert paths.TUI_STATE_PATH == paths.STATE_DIR / "tui_state.json"
    assert paths.CRON_STATE_PATH == paths.STATE_DIR / "cron_state.json"
    assert paths.SESSION_MAP_PATH == paths.STATE_DIR / "session_map.json"
    assert paths.CHIPTUNES_FAVORITES_PATH == paths.STATE_DIR / "chiptunes-favorites.json"
    assert paths.RUNTIME_SETTINGS_PATH == paths.STATE_DIR / "runtime-settings.json"


def test_home_defaults_to_user_teleclaude_dir_when_env_unset() -> None:
    env = os.environ.copy()
    env.pop("TELECLAUDE_HOME", None)

    # Child interpreter required: teleclaude.paths resolves constants at import time.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path\n"
                "from teleclaude import paths\n"
                "print(paths.TELECLAUDE_HOME)\n"
                "print(Path('~/.teleclaude').expanduser())"
            ),
        ],
        cwd=paths.REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    actual, expected = [Path(line) for line in result.stdout.splitlines()]
    assert actual == expected
