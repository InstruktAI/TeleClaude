"""Functional RED specs for todo rename atomicity."""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypedDict, cast

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import ARTIFACT_REQUIREMENTS, WORKTREE_DIR
from teleclaude.core.db import Db
from teleclaude.core.next_machine import delivery as delivery_module
from teleclaude.core.todos_db import TodosDb
from teleclaude.git import Repo

pytestmark = pytest.mark.functional

_OLD_SLUG = "old-slug"
_NEW_SLUG = "new-slug"
_TELECLAUDE_DIR = ".teleclaude"
_GIT_DIR = ".git"
_GIT_LOGS_DIR = "logs"
_WORKTREE_CONTENT = "worktree contents\n"
_WORKSPACE_CONTENT = "workspace contents\n"
_RenameExecutor = Callable[[Db, str, str, str], Awaitable[str]]


class _RoadmapDumpRow(TypedDict):
    slug: str
    group_slug: str | None
    status: str
    children: str | None


class _RoadmapDepDumpRow(TypedDict):
    slug: str
    depends_on: str


class _TodoStateDumpRow(TypedDict):
    slug: str
    state: str


class _TodoArtifactDumpRow(TypedDict):
    slug: str
    name: str
    content: str
    digest: str


class _TodosDump(TypedDict):
    roadmap: list[_RoadmapDumpRow]
    roadmap_deps: list[_RoadmapDepDumpRow]
    todo_state: list[_TodoStateDumpRow]
    todo_artifacts: list[_TodoArtifactDumpRow]
    todo_artifact_versions: list[_TodoArtifactDumpRow]


class _ProjectSnapshot(TypedDict):
    files: dict[str, bytes]
    todos: _TodosDump


class _GitSurfaceSnapshot(TypedDict):
    project_files: dict[str, bytes]
    remote_files: dict[str, bytes]
    worktrees: list[dict[str, str]]
    branches: list[str]
    remote_heads: list[str]


async def _main_db(project_root: Path) -> Db:
    database = Db(str(project_root / ".teleclaude" / "main.db"))
    await database.initialize()
    return database


async def _todos_db(project_root: Path) -> TodosDb:
    database = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
    await database.initialize()
    return database


async def _seed_project(project_root: Path, todos_db: TodosDb) -> Path:
    await todos_db.add_to_roadmap("upstream")
    await todos_db.add_to_roadmap(_OLD_SLUG, after=["upstream"])
    await todos_db.add_to_roadmap("downstream", after=[_OLD_SLUG])
    await todos_db.write_state(_OLD_SLUG, {"kind": "feature", "lifecycle_phase": "prepared"})
    await todos_db.write_artifact(_OLD_SLUG, ARTIFACT_REQUIREMENTS, "requirements before rename")

    trees_dir = project_root / "trees" / _OLD_SLUG
    trees_dir.mkdir(parents=True, exist_ok=True)
    (trees_dir / "work.txt").write_text(_WORKTREE_CONTENT, encoding="utf-8")
    workspace_dir = project_root / "workspace" / _OLD_SLUG
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "artifact.txt").write_text(_WORKSPACE_CONTENT, encoding="utf-8")

    snippet_path = project_root / "docs" / "project" / "spec" / "rename-contract.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/rename-contract\n"
            "type: spec\n"
            "scope: project\n"
            "description: Rename contract\n"
            "status: target\n"
            "delivered_by: [old-slug]\n"
            "---\n"
            "# Rename Contract\n"
            "## What it is\n"
            "Body keeps old-slug as prose.\n"
            "## Canonical fields\n"
            "Fields stay stable.\n"
        ),
        encoding="utf-8",
    )
    return snippet_path


def _init_git_project(project_root: Path, remote_root: Path) -> Repo:
    repo = Repo.init(str(project_root))
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test")
    repo.git.config("commit.gpgsign", "false")
    (project_root / "README.md").write_text("base\n", encoding="utf-8")
    repo.git.add("README.md")
    repo.git.commit("-m", "initial commit")
    repo.git.branch(_OLD_SLUG)
    Repo.init(str(remote_root), bare=True)
    repo.create_remote("origin", str(remote_root))
    repo.git.push("origin", f"{_OLD_SLUG}:{_OLD_SLUG}")
    (project_root / WORKTREE_DIR).mkdir(parents=True, exist_ok=True)
    repo.git.worktree("add", str(project_root / WORKTREE_DIR / _OLD_SLUG), _OLD_SLUG)
    return repo


def _stable_file_bytes(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_dir() or _TELECLAUDE_DIR in relative.parts:
            continue
        if _GIT_DIR in relative.parts and _GIT_LOGS_DIR in relative.parts:
            continue
        files[relative.as_posix()] = path.read_bytes()
    return files


def _worktree_entries(repo: Repo) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in repo.git.worktree("list", "--porcelain").splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def _branch_names(repo: Repo) -> list[str]:
    return sorted(name for name in repo.git.branch("--format=%(refname:short)").splitlines() if name)


def _remote_heads(remote_root: Path) -> list[str]:
    remote_repo = Repo(str(remote_root))
    output = remote_repo.git.for_each_ref("--format=%(refname:short)", "refs/heads")
    return sorted(name for name in output.splitlines() if name)


def _git_surface_snapshot(project_root: Path, remote_root: Path) -> _GitSurfaceSnapshot:
    repo = Repo(str(project_root))
    return {
        "project_files": _stable_file_bytes(project_root),
        "remote_files": _stable_file_bytes(remote_root),
        "worktrees": _worktree_entries(repo),
        "branches": _branch_names(repo),
        "remote_heads": _remote_heads(remote_root),
    }


def _commit_snippet_baseline(project_root: Path, snippet_path: Path) -> None:
    repo = Repo(str(project_root))
    repo.git.add(snippet_path.relative_to(project_root).as_posix())
    repo.git.commit("-m", "seed rename snippet")


def _project_files(project_root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(project_root.rglob("*")):
        if path.is_dir() or _TELECLAUDE_DIR in path.parts:
            continue
        files[str(path.relative_to(project_root))] = path.read_bytes()
    return files


def _roadmap_row(row: tuple[object, ...]) -> _RoadmapDumpRow:
    return {
        "slug": str(row[0]),
        "group_slug": str(row[1]) if row[1] is not None else None,
        "status": str(row[2]),
        "children": str(row[3]) if row[3] is not None else None,
    }


def _roadmap_dep_row(row: tuple[object, ...]) -> _RoadmapDepDumpRow:
    return {"slug": str(row[0]), "depends_on": str(row[1])}


def _todo_state_row(row: tuple[object, ...]) -> _TodoStateDumpRow:
    return {"slug": str(row[0]), "state": str(row[1])}


def _todo_artifact_row(row: tuple[object, ...]) -> _TodoArtifactDumpRow:
    return {
        "slug": str(row[0]),
        "name": str(row[1]),
        "content": str(row[2]),
        "digest": str(row[3]),
    }


def _todos_dump(todos_db: TodosDb) -> _TodosDump:
    conn = todos_db._sync_conn()  # pylint: disable=protected-access
    try:
        return {
            "roadmap": [
                _roadmap_row(row)
                for row in conn.execute(
                    "SELECT slug, group_slug, status, children FROM roadmap ORDER BY slug, status"  # guard: raw-sql
                ).fetchall()
            ],
            "roadmap_deps": [
                _roadmap_dep_row(row)
                for row in conn.execute(
                    "SELECT slug, depends_on FROM roadmap_deps ORDER BY slug, depends_on"  # guard: raw-sql
                ).fetchall()
            ],
            "todo_state": [
                _todo_state_row(row)
                for row in conn.execute("SELECT slug, state FROM todo_state ORDER BY slug").fetchall()  # guard: raw-sql
            ],
            "todo_artifacts": [
                _todo_artifact_row(row)
                for row in conn.execute(
                    "SELECT slug, name, content, digest FROM todo_artifacts ORDER BY slug, name"  # guard: raw-sql
                ).fetchall()
            ],
            "todo_artifact_versions": [
                _todo_artifact_row(row)
                for row in conn.execute(
                    "SELECT slug, name, content, digest FROM todo_artifact_versions ORDER BY slug, name, version_id"  # guard: raw-sql
                ).fetchall()
            ],
        }
    finally:
        conn.close()


def _snapshot_project(project_root: Path, todos_db: TodosDb) -> _ProjectSnapshot:
    return {"files": _project_files(project_root), "todos": _todos_dump(todos_db)}


async def _run_rename(
    project_root: Path,
    todos_db: TodosDb,
    main_db: Db,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    module = importlib.import_module("teleclaude.core.next_machine.rename")

    async def _get_todos_db(_cwd: str) -> TodosDb:
        return todos_db

    monkeypatch.setattr(module, "get_todos_db", _get_todos_db, raising=False)
    executor = cast(_RenameExecutor, module.execute_todo_rename)
    return await executor(main_db, _OLD_SLUG, _NEW_SLUG, str(project_root))


async def test_execute_todo_rename_refuses_on_dirty_snippet_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    snippet_path.write_text(snippet_path.read_text(encoding="utf-8") + "\nDirty edit.\n", encoding="utf-8")
    before = (_todos_dump(todos_db), snippet_path.read_bytes())

    try:
        result = await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert (_todos_dump(todos_db), snippet_path.read_bytes()) == before
        assert result == snapshot
    finally:
        await todos_db.close()
        await main_db.close()


async def test_execute_todo_rename_refuses_on_hook_env_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before = (_todos_dump(todos_db), snippet_path.read_bytes())
    rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
    original_run_git_cmd = delivery_module._run_git_cmd  # pylint: disable=protected-access

    def _fail_repo_sanity(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args == ["rev-parse", "--git-dir"]:
            return 1, "", "injected git sanity failure"
        return original_run_git_cmd(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(rename_module, "_run_git_cmd", _fail_repo_sanity, raising=False)

    try:
        result = await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert (_todos_dump(todos_db), snippet_path.read_bytes()) == before
        assert result == snapshot
    finally:
        await todos_db.close()
        await main_db.close()


async def test_execute_todo_rename_commits_snippet_mutations_to_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    repo = _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    unrelated_path = project_root / "unrelated.md"
    unrelated_path.write_text("unrelated staged edit\n", encoding="utf-8")
    repo.git.add(unrelated_path.relative_to(project_root).as_posix())

    try:
        await _run_rename(project_root, todos_db, main_db, monkeypatch)

        snippet_pathspec = snippet_path.relative_to(project_root).as_posix()
        assert not repo.git.status("--porcelain", "--", snippet_pathspec)
        assert repo.git.diff("--cached", "--name-only").splitlines() == [unrelated_path.name]
        assert repo.git.log("-1", "--format=%s") == snapshot
        assert repo.git.show("--stat", "--format=%s", "HEAD") == snapshot
    finally:
        await todos_db.close()
        await main_db.close()


async def test_execute_todo_rename_compensates_on_post_db_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    repo = _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before_todos = _todos_dump(todos_db)
    snippet_pathspec = snippet_path.relative_to(project_root).as_posix()
    rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
    original_run_git_cmd = rename_module._run_git_cmd  # pylint: disable=protected-access

    def _fail_commit(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args and args[0] == "commit":
            return 1, "", "injected commit failure"
        return original_run_git_cmd(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(rename_module, "_run_git_cmd", _fail_commit, raising=False)

    try:
        result = await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert _todos_dump(todos_db) == before_todos
        assert not repo.git.status("--porcelain", "--", snippet_pathspec)
        assert result == snapshot
    finally:
        await todos_db.close()
        await main_db.close()


async def test_execute_todo_rename_compensates_when_snippet_gets_dirty_after_precondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    repo = _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before = (_todos_dump(todos_db), snippet_path.read_bytes())
    snippet_pathspec = snippet_path.relative_to(project_root).as_posix()
    rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
    original_rewrite_and_commit = rename_module._rewrite_and_commit_delivered_by  # pylint: disable=protected-access

    def _dirty_after_precondition(project_root_arg: Path, old_slug: str, new_slug: str) -> list[object]:
        snippet_path.write_text(snippet_path.read_text(encoding="utf-8") + "\nConcurrent edit.\n", encoding="utf-8")
        return original_rewrite_and_commit(project_root_arg, old_slug, new_slug)

    monkeypatch.setattr(rename_module, "_rewrite_and_commit_delivered_by", _dirty_after_precondition, raising=False)

    try:
        result = await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert (_todos_dump(todos_db), snippet_path.read_bytes()) == before
        assert not repo.git.status("--porcelain", "--", snippet_pathspec)
        assert result == snapshot
    finally:
        await todos_db.close()
        await main_db.close()


async def test_execute_todo_rename_compensates_db_when_snippet_index_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before_todos = _todos_dump(todos_db)
    rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
    original_run_git_cmd = rename_module._run_git_cmd  # pylint: disable=protected-access

    def _fail_commit(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args and args[0] == "commit":
            return 1, "", "injected commit failure"
        return original_run_git_cmd(args, cwd=cwd, timeout=timeout)

    def _fail_index_restore(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected index restore failure")

    monkeypatch.setattr(rename_module, "_run_git_cmd", _fail_commit, raising=False)
    monkeypatch.setattr(rename_module, "_sync_snippet_index_to_head", _fail_index_restore, raising=False)

    try:
        with pytest.raises(RuntimeError):
            await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert _todos_dump(todos_db) == before_todos
    finally:
        await todos_db.close()
        await main_db.close()


async def test_git_managed_happy_path_renames_worktree_branch_remote_and_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)

    try:
        await _run_rename(project_root, todos_db, main_db, monkeypatch)

        git_snapshot = _git_surface_snapshot(project_root, remote_root)
        worktree_paths = {entry["worktree"] for entry in git_snapshot["worktrees"]}
        worktree_branches = {entry.get("branch") for entry in git_snapshot["worktrees"]}
        assert str(project_root / WORKTREE_DIR / _NEW_SLUG) in worktree_paths
        assert str(project_root / WORKTREE_DIR / _OLD_SLUG) not in worktree_paths
        assert f"refs/heads/{_NEW_SLUG}" in worktree_branches
        assert f"refs/heads/{_OLD_SLUG}" not in worktree_branches
        assert _NEW_SLUG in git_snapshot["branches"]
        assert _OLD_SLUG not in git_snapshot["branches"]
        assert git_snapshot["remote_heads"] == [_NEW_SLUG]
        assert (project_root / WORKTREE_DIR / _NEW_SLUG / "work.txt").read_text(encoding="utf-8") == _WORKTREE_CONTENT
        assert (project_root / "workspace" / _NEW_SLUG / "artifact.txt").read_text(
            encoding="utf-8"
        ) == _WORKSPACE_CONTENT
    finally:
        await todos_db.close()
        await main_db.close()


def test_git_push_failure_restores_git_surfaces_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    before = _git_surface_snapshot(project_root, remote_root)

    original_run_git_cmd = delivery_module._run_git_cmd  # pylint: disable=protected-access

    def _fail_push(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args[:2] == ["push", "origin"] and len(args) == 3 and args[2] == f"{_OLD_SLUG}:{_NEW_SLUG}":
            return 1, "", "injected push failure"
        return original_run_git_cmd(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(delivery_module, "_run_git_cmd", _fail_push)

    with pytest.raises(RuntimeError):
        delivery_module.move_todo_slug_surfaces(str(project_root), _OLD_SLUG, _NEW_SLUG)

    assert _git_surface_snapshot(project_root, remote_root) == before


def test_git_worktree_move_failure_restores_git_surfaces_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    before = _git_surface_snapshot(project_root, remote_root)

    original_run_git_cmd = delivery_module._run_git_cmd  # pylint: disable=protected-access

    def _fail_worktree_move(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args[:2] == ["worktree", "move"] and str(project_root / WORKTREE_DIR / _OLD_SLUG) in args:
            return 1, "", "injected worktree move failure"
        return original_run_git_cmd(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(delivery_module, "_run_git_cmd", _fail_worktree_move)

    with pytest.raises(RuntimeError):
        delivery_module.move_todo_slug_surfaces(str(project_root), _OLD_SLUG, _NEW_SLUG)

    assert _git_surface_snapshot(project_root, remote_root) == before


def test_git_branch_rename_failure_restores_git_surfaces_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    before = _git_surface_snapshot(project_root, remote_root)

    original_run_git_cmd = delivery_module._run_git_cmd  # pylint: disable=protected-access

    def _fail_branch_rename(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        if args == ["branch", "-m", _OLD_SLUG, _NEW_SLUG]:
            return 1, "", "injected branch rename failure"
        return original_run_git_cmd(args, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(delivery_module, "_run_git_cmd", _fail_branch_rename)

    with pytest.raises(RuntimeError):
        delivery_module.move_todo_slug_surfaces(str(project_root), _OLD_SLUG, _NEW_SLUG)

    assert _git_surface_snapshot(project_root, remote_root) == before


def test_workspace_move_failure_restores_git_surfaces_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    workspace_dir = project_root / "workspace" / _OLD_SLUG
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "artifact.txt").write_text(_WORKSPACE_CONTENT, encoding="utf-8")
    before = _git_surface_snapshot(project_root, remote_root)

    original_move_path = delivery_module._move_path  # pylint: disable=protected-access

    def _fail_workspace_move(source: Path, destination: Path) -> None:
        if source == workspace_dir:
            raise RuntimeError("injected workspace move failure")
        original_move_path(source, destination)

    monkeypatch.setattr(delivery_module, "_move_path", _fail_workspace_move)

    with pytest.raises(RuntimeError):
        delivery_module.move_todo_slug_surfaces(str(project_root), _OLD_SLUG, _NEW_SLUG)

    assert _git_surface_snapshot(project_root, remote_root) == before


async def test_db_leg_failure_restores_project_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before = (_todos_dump(todos_db), snippet_path.read_bytes())

    async def _raise_db_leg(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("injected todos.db leg failure")

    monkeypatch.setattr(todos_db, "rename_state_slug", _raise_db_leg, raising=False)

    try:
        with pytest.raises(RuntimeError):
            await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert (_todos_dump(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()
        await main_db.close()


async def test_frontmatter_leg_failure_restores_project_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before = (_todos_dump(todos_db), snippet_path.read_bytes())

    def _raise_frontmatter_leg(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("injected frontmatter leg failure")

    try:
        rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
        monkeypatch.setattr(rename_module, "rewrite_delivered_by_slug", _raise_frontmatter_leg, raising=False)

        result = await _run_rename(project_root, todos_db, main_db, monkeypatch)

        git_snapshot = _git_surface_snapshot(project_root, remote_root)
        worktree_paths = {entry["worktree"] for entry in git_snapshot["worktrees"]}
        assert (_todos_dump(todos_db), snippet_path.read_bytes()) == before
        assert str(project_root / WORKTREE_DIR / _OLD_SLUG) in worktree_paths
        assert str(project_root / WORKTREE_DIR / _NEW_SLUG) not in worktree_paths
        assert _OLD_SLUG in git_snapshot["branches"]
        assert _NEW_SLUG not in git_snapshot["branches"]
        assert git_snapshot["remote_heads"] == [_OLD_SLUG]
        assert result == snapshot
    finally:
        await todos_db.close()
        await main_db.close()


async def test_local_fs_leg_failure_restores_project_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    remote_root = tmp_path / "remote.git"
    _init_git_project(project_root, remote_root)
    todos_db = await _todos_db(project_root)
    main_db = await _main_db(project_root)
    snippet_path = await _seed_project(project_root, todos_db)
    _commit_snippet_baseline(project_root, snippet_path)
    before = (_todos_dump(todos_db), snippet_path.read_bytes(), _git_surface_snapshot(project_root, remote_root))

    def _raise_local_fs_leg(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("injected local filesystem leg failure")

    try:
        rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
        monkeypatch.setattr(rename_module, "move_todo_slug_surfaces", _raise_local_fs_leg, raising=False)

        with pytest.raises(RuntimeError):
            await _run_rename(project_root, todos_db, main_db, monkeypatch)

        assert (
            _todos_dump(todos_db),
            snippet_path.read_bytes(),
            _git_surface_snapshot(project_root, remote_root),
        ) == before
    finally:
        await todos_db.close()
        await main_db.close()
