"""Functional tests for sync() self-registering a publishing project's root.

Spec: docs/project/spec/feature/context/sync-pipeline-orchestration.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.sync as sync
from teleclaude.cli.telec.handlers import misc
from teleclaude.git import Repo
from teleclaude.project_manifest import load_roots

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/sync-pipeline-orchestration"
_ARD_SPEC = "project/spec/feature/context/agent-runtime-deployment"


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
    ``resolve_project_root`` exercise the actual gitdir-walk, so a test asserting
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


def _init_worktree_at(main_root: Path, repo: Repo, *, worktree_name: str, branch: str) -> Path:
    """Add a linked worktree at ``trees/<worktree_name>`` off ``main_root``.

    The `trees/<name>` shape (not an arbitrary sibling path) is what
    `is_slug_worktree`/`is_integration_worktree` key off of — real production
    layout, not an ad hoc test path.
    """
    worktree_path = main_root / "trees" / worktree_name
    repo.git.worktree("add", "-b", branch, str(worktree_path), "HEAD")
    return worktree_path.resolve()


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


@pytest.mark.spec(_SPEC, "UC-SPO4")
@pytest.mark.spec(_ARD_SPEC, "UC-ARD3")
def test_deploy_mode_sync_is_refused_from_a_slug_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    """Drives the real `_handle_sync` CLI boundary — not a direct `sync.sync()`
    call — so it exercises the actual invocation-cwd canonicalization that
    `resolve_invocation_project_root()` performs, the same canonicalization
    that let a slug-worktree deploy through in the reported regression."""
    manifest_path = _prepare(tmp_path, monkeypatch)
    main_root = _project(tmp_path / "main", publishes=["erp"])
    repo = Repo.init(main_root)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Sync Test")
    repo.git.config("user.email", "sync-test@example.test")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    main_root = main_root.resolve()
    slug_worktree = _init_worktree_at(main_root, repo, worktree_name="my-slug", branch="my-slug")
    integration_worktree = _init_worktree_at(main_root, repo, worktree_name="_integration", branch="integration")

    # Deploy-mode sync from the main checkout composes normally.
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(main_root))
    misc._handle_sync([])
    assert load_roots(manifest_path) == [main_root]

    # Deploy-mode sync from the integration worktree is unaffected.
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(integration_worktree))
    misc._handle_sync([])
    assert load_roots(manifest_path) == [main_root]

    # --skip-deploy from the slug worktree still validates; no refusal, no registration.
    monkeypatch.setenv("TELEC_INVOCATION_CWD", str(slug_worktree))
    misc._handle_sync(["--skip-deploy"])
    assert load_roots(manifest_path) == [main_root]

    # Deploy-mode sync from the slug worktree is refused before the pipeline runs:
    # no validation, index build, or distribution — asserted by making the pipeline
    # entry point itself raise if reached.
    monkeypatch.setattr(
        misc,
        "_run_sync",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("sync pipeline must not run")),
    )
    with pytest.raises(SystemExit) as exc_info:
        misc._handle_sync([])

    # The worktree path is a per-run tmp_path; redact it before snapshotting
    # per software-development/procedure/snapshot-testing (nondeterministic values).
    normalized_message = str(exc_info.value).replace(str(slug_worktree), "<slug-worktree>")
    assert {"refusal_message": normalized_message} == snapshot
    assert load_roots(manifest_path) == [main_root]
