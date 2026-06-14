"""Functional coverage for delivered-slug cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from pathlib import Path
from typing import Any, cast

import pytest

import teleclaude.core.lifecycle as lifecycle_module
import teleclaude.core.next_machine.delivery as delivery_module
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.integration.checkpoint import IntegrationCheckpoint, IntegrationPhase, _now_iso
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.step_functions import _step_idle
from teleclaude.core.lifecycle import DaemonLifecycle
from teleclaude.core.models import ProjectInfo
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.todos_db import close_todos_db_instances
from teleclaude.git import Repo

_SPEC = "project/spec/feature/workflow/worktree-prep-lifecycle"
_WORKTREE_PORCELAIN_KEY = "worktree "
_TRASH_RECLAIM_TASK = "worktree-trash-reclaim"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    await close_todos_db_instances()
    yield
    await close_todos_db_instances()


def _init_repo(project_root: Path) -> Repo:
    project_root.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(project_root)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Delivery Test")
    repo.git.config("user.email", "delivery-test@example.test")
    (project_root / "README.md").write_text("initial\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    return repo


def _add_worktree(repo: Repo, project_root: Path, slug: str) -> Path:
    worktree_path = project_root / WORKTREE_DIR / slug
    worktree_path.parent.mkdir(parents=True)
    repo.git.worktree("add", "-b", slug, str(worktree_path), "HEAD")
    return worktree_path


def _listed_worktree_paths(repo: Repo) -> set[Path]:
    output = repo.git.worktree("list", "--porcelain")
    return {
        Path(line.removeprefix(_WORKTREE_PORCELAIN_KEY)).resolve()
        for line in output.splitlines()
        if line.startswith(_WORKTREE_PORCELAIN_KEY)
    }


def _assert_worktree_admin_removed(repo: Repo, worktree_path: Path, slug: str) -> None:
    assert not worktree_path.exists()
    assert worktree_path.resolve() not in _listed_worktree_paths(repo)
    assert not (Path(repo.git_dir) / "worktrees" / slug).exists()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "delivered-slug-cleanup-removes-worktree")
def test_cleanup_delivered_slug_removes_worktree_and_admin_entry(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    repo = _init_repo(project_root)
    slug = "delivered-cleanup"
    worktree_path = _add_worktree(repo, project_root, slug)

    cleanup_delivered_slug(str(project_root), slug, remove_remote_branch=False)

    _assert_worktree_admin_removed(repo, worktree_path, slug)


@pytest.mark.functional
def test_cleanup_delivered_slug_unlocks_locked_worktree_before_prune(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    repo = _init_repo(project_root)
    slug = "locked-cleanup"
    worktree_path = _add_worktree(repo, project_root, slug)
    repo.git.worktree("lock", str(worktree_path))

    cleanup_delivered_slug(str(project_root), slug, remove_remote_branch=False)

    _assert_worktree_admin_removed(repo, worktree_path, slug)


@pytest.mark.functional
def test_reclaim_worktree_trash_removes_entries_without_following_symlink(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    trash_dir = project_root / WORKTREE_DIR / ".trash"
    trash_dir.mkdir(parents=True)
    trashed_worktree = trash_dir / "trashed-worktree"
    trashed_worktree.mkdir()
    (trashed_worktree / "payload.txt").write_text("payload\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    (trash_dir / "outside-link").symlink_to(outside, target_is_directory=True)

    failures = delivery_module.reclaim_worktree_trash(str(project_root))

    assert failures == []
    assert list(trash_dir.iterdir()) == []
    assert sentinel.exists()


@pytest.mark.functional
def test_reclaim_worktree_trash_returns_failed_entries_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    trash_dir = project_root / WORKTREE_DIR / ".trash"
    failed_entry = trash_dir / "blocked"
    removed_entry = trash_dir / "removed"
    failed_entry.mkdir(parents=True)
    removed_entry.mkdir()
    original_rmtree = delivery_module.shutil.rmtree

    def fake_rmtree(path: str | Path) -> None:
        entry = Path(path)
        if entry == failed_entry:
            raise PermissionError("blocked")
        original_rmtree(entry)

    monkeypatch.setattr(delivery_module.shutil, "rmtree", fake_rmtree)

    failures = delivery_module.reclaim_worktree_trash(str(project_root))

    assert failures == [str(failed_entry)]
    assert failed_entry.exists()
    assert not removed_entry.exists()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "delivered-slug-cleanup-is-idempotent")
def test_cleanup_delivered_slug_is_idempotent_after_worktree_removed(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    repo = _init_repo(project_root)
    slug = "idempotent-cleanup"
    worktree_path = _add_worktree(repo, project_root, slug)

    cleanup_delivered_slug(str(project_root), slug, remove_remote_branch=False)
    cleanup_delivered_slug(str(project_root), slug, remove_remote_branch=False)

    _assert_worktree_admin_removed(repo, worktree_path, slug)


@pytest.mark.functional
def test_step_idle_reclaims_trash_without_delivered_slugs(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    trash_entry = project_root / WORKTREE_DIR / ".trash" / "stale-entry"
    trash_entry.mkdir(parents=True)
    (trash_entry / "payload.txt").write_text("payload\n", encoding="utf-8")
    now = _now_iso()
    checkpoint = IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at=now,
        last_updated_at=now,
        error_context=None,
        pre_merge_head=None,
        warnings=[],
    )

    _step_idle(
        checkpoint=checkpoint,
        checkpoint_path=project_root / "integrate-state.json",
        lease_store=IntegrationLeaseStore(state_path=project_root / "lease.json"),
        session_id="idle-session",
        slug=None,
        cwd=str(project_root),
        started=0.0,
    )

    assert not trash_entry.exists()


class _CapturingTaskRegistry:
    def __init__(self) -> None:
        self.spawned: list[tuple[Coroutine[object, object, object], str | None]] = []

    def spawn(
        self,
        coro: Coroutine[object, object, object],
        name: str | None = None,
    ) -> asyncio.Task[object]:
        self.spawned.append((coro, name))
        return cast(asyncio.Task[object], object())


class _LifecycleClient:
    transport: object | None = None

    async def reconcile_outstanding_final_outputs(self, _computer_name: str) -> int:
        return 0


async def _noop_async() -> None:
    return None


def _make_lifecycle(task_registry: object) -> DaemonLifecycle:
    return DaemonLifecycle(
        client=cast(Any, _LifecycleClient()),
        cache=cast(Any, object()),
        shutdown_event=asyncio.Event(),
        task_registry=cast(Any, task_registry),
        log_background_task_exception=lambda _name: lambda _task: None,
        init_voice_handler=lambda: None,
        event_platform_init=_noop_async,
        api_restart_max=3,
        api_restart_window_s=60.0,
        api_restart_backoff_s=1.0,
    )


@pytest.mark.functional
def test_startup_reclaim_schedules_background_task_without_running_sync_reclaim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _CapturingTaskRegistry()
    lifecycle = _make_lifecycle(registry)
    called_paths: list[str] = []

    def record_reclaim(path: str) -> list[str]:
        called_paths.append(path)
        return []

    monkeypatch.setattr(lifecycle_module, "reclaim_worktree_trash", record_reclaim, raising=False)

    lifecycle._schedule_worktree_trash_reclaim()

    assert called_paths == []
    assert len(registry.spawned) == 1
    coro, task_name = registry.spawned[0]
    assert task_name == _TRASH_RECLAIM_TASK
    coro.close()


@pytest.mark.functional
async def test_startup_reclaim_background_task_drains_each_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    reclaimed_paths: list[str] = []

    async def list_projects() -> list[ProjectInfo]:
        return [ProjectInfo(name="project", path=str(project_root))]

    def record_reclaim(path: str) -> list[str]:
        reclaimed_paths.append(path)
        return []

    monkeypatch.setattr(lifecycle_module.command_handlers, "list_projects_with_todos", list_projects)
    monkeypatch.setattr(lifecycle_module, "reclaim_worktree_trash", record_reclaim, raising=False)

    lifecycle = _make_lifecycle(_CapturingTaskRegistry())
    await lifecycle._reclaim_worktree_trash_for_local_projects()

    assert reclaimed_paths == [str(project_root)]
