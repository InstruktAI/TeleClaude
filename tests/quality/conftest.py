"""Shared fixtures for the quality test domain."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.git import Repo

_TELECLAUDE_YML = "business:\n  domains:\n    software-development: docs\n"


def _init_checkout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    Repo.init(root)
    (root / "teleclaude.yml").write_text(_TELECLAUDE_YML, encoding="utf-8")


@pytest.fixture(autouse=True)
def _init_project_git(tmp_path: Path) -> None:
    """Give bare ``tmp_path`` and ``tmp_path / "project"`` real git metadata.

    ``resolve_project_root`` requires genuine git metadata plus
    ``teleclaude.yml`` to recognize a checkout; this domain uses both bare
    ``tmp_path`` and ``tmp_path / "project"`` as a project root across
    different test files.
    """
    _init_checkout(tmp_path)
    _init_checkout(tmp_path / "project")
