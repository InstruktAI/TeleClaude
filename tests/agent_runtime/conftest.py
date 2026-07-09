"""Agent-runtime test fixtures.

The shared real-app ``api`` fixture lives in the root ``tests/conftest.py``; this
module keeps only the agent-runtime-scoped git-init fixture that fail-loud
``resolve_project_root`` requires.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.git import Repo


@pytest.fixture(autouse=True)
def _init_project_git(tmp_path: Path) -> None:
    """Give bare ``tmp_path`` real git metadata so ``resolve_project_root`` resolves it.

    The ``api`` fixture wires ``default_working_dir=str(tmp_path)``, and this
    domain's tests broadly pass bare ``tmp_path`` as a session/todo project root;
    ``resolve_project_root`` requires genuine git metadata plus ``teleclaude.yml``
    to recognize a checkout, or it fails loud rather than resolving to itself.
    """
    Repo.init(tmp_path)
    (tmp_path / "teleclaude.yml").write_text(
        "business:\n  domains:\n    software-development: docs\n", encoding="utf-8"
    )
