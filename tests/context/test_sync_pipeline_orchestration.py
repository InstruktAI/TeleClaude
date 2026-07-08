"""Functional tests for sync() self-registering a publishing project's root.

Spec: docs/project/spec/feature/context/sync-pipeline-orchestration.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.sync as sync
from teleclaude.git import Repo
from teleclaude.project_manifest import load_roots

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/sync-pipeline-orchestration"


def _project(root: Path, *, publishes: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if publishes:
        items = "\n".join(f"    - {domain}" for domain in publishes)
        body = f"project_slug: {root.name}\nbusiness:\n  publishes:\n{items}\n"
    else:
        body = f"project_slug: {root.name}\nbusiness: {{}}\n"
    (root / "teleclaude.yml").write_text(body, encoding="utf-8")
    return root


def _init_publisher_with_worktree(root: Path, *, publishes: list[str]) -> tuple[Path, Path]:
    """Create a real main checkout plus a linked git worktree declaring ``publishes``.

    Returns ``(main_root, worktree_path)``. Real git metadata makes
    ``resolve_state_root`` exercise the actual gitdir-walk, so a test asserting
    against the worktree path (instead of the resolved main root) would pass even
    if the implementation registered the invocation path unresolved.
    """
    main_root = _project(root / "main", publishes=publishes)
    repo = Repo.init(main_root)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Sync Test")
    repo.git.config("user.email", "sync-test@example.test")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    worktree_path = (root / "worktree").resolve()
    repo.git.worktree("add", "-b", "feature", str(worktree_path), "HEAD")
    return main_root.resolve(), worktree_path


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the manifest at a tmp file and fake only the distribute subprocess boundary."""
    manifest_path = tmp_path / "projects.yaml"
    monkeypatch.setattr("teleclaude.project_manifest.MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(sync, "_run_distribute", lambda _project_root: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return manifest_path


@pytest.mark.spec(_SPEC, "UC-SPO1")
def test_publishing_sync_registers_publisher_idempotently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    main_root, worktree_path = _init_publisher_with_worktree(tmp_path, publishes=["erp"])

    # Sync is invoked from the linked worktree; the manifest must record the
    # owning main checkout root, not the worktree path passed as project_root.
    assert sync.sync(worktree_path) is True
    assert load_roots(manifest_path) == [main_root]

    # Running again does not add a duplicate manifest entry.
    assert sync.sync(worktree_path) is True
    assert load_roots(manifest_path) == [main_root]


@pytest.mark.spec(_SPEC, "UC-SPO2")
def test_skip_deploy_registers_no_publisher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    project = _project(tmp_path / "proj", publishes=["erp"])

    assert sync.sync(project, skip_deploy=True) is True

    assert load_roots(manifest_path) == []


@pytest.mark.spec(_SPEC, "UC-SPO3")
def test_non_publishing_project_registers_no_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    project = _project(tmp_path / "proj", publishes=[])

    assert sync.sync(project) is True

    assert load_roots(manifest_path) == []
