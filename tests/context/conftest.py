"""Shared fixtures for the context test domain."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.git import Repo


@pytest.fixture(autouse=True)
def _init_project_git(tmp_path: Path) -> None:
    """Give bare ``tmp_path`` real git metadata so ``resolve_project_root`` resolves it.

    ``graph_path``/``manifest_path`` route through the strict resolver, which
    requires genuine git metadata plus ``teleclaude.yml`` to recognize a
    checkout; this domain uses bare ``tmp_path`` as its project root directly.
    """
    Repo.init(tmp_path)
    (tmp_path / "teleclaude.yml").write_text(
        "business:\n  domains:\n    software-development: docs\n", encoding="utf-8"
    )
