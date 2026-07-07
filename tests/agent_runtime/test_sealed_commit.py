"""Functional coverage for sealed commit in-process gates."""

from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from teleclaude.cli.telec.handlers import code
from teleclaude.git import GIT_EXECUTABLE
from teleclaude.quality.scope import DirtyOp, DirtyPath, WorkspaceScopeKind, WorkspaceScopeResolution

_SPEC = "project/spec/feature/agent_runtime/sealed-commit"
_MESSAGE_FILE_FLAG = "-F"
_MESSAGE_FILE_SENTINEL = "<message-file>"


class _FakeGit:
    def __init__(self, records: list[object]) -> None:
        self.records = records

    def commit(self, *args: str, with_extended_output: bool) -> tuple[int, str, str]:
        normalized_args = list(args)
        if _MESSAGE_FILE_FLAG in normalized_args:
            msg_index = normalized_args.index(_MESSAGE_FILE_FLAG) + 1
            normalized_args[msg_index] = _MESSAGE_FILE_SENTINEL
        self.records.append(("commit", tuple(normalized_args), with_extended_output))
        return 0, "committed", ""

    def show(self, *args: str) -> str:
        self.records.append(("show", args))
        return "tracked.py\n"


class _FakeRepo:
    records: list[object] = []

    def __init__(self, _project_root: str) -> None:
        self.git_dir = str(Path(_project_root) / ".git")
        self.git = _FakeGit(self.records)


def _scope(*dirty: DirtyPath) -> WorkspaceScopeResolution:
    return WorkspaceScopeResolution(
        kind=WorkspaceScopeKind.WORKTREE,
        has_session_identity=True,
        dirty_paths=dirty,
        scoped_dirty_paths=tuple(path.path for path in dirty),
        scoped_existing_paths=tuple(path.path for path in dirty if path.op is not DirtyOp.DELETED),
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch, scope: WorkspaceScopeResolution) -> list[object]:
    records: list[object] = []
    _FakeRepo.records = records
    monkeypatch.setattr(code, "wait_for_index_lock_clear", lambda _project_root: records.append("lock-clear"))
    monkeypatch.setattr(code, "resolve_workspace_scope_resolution", lambda _project_root: scope)
    monkeypatch.setattr(code, "_working_tree_snapshot", lambda _project_root: code._WorkingTreeSnapshot())
    monkeypatch.setattr(code, "_check_commit_message", lambda _message, _project_root: records.append("message"))
    monkeypatch.setattr(code, "handle_format", lambda paths: records.append(("format", paths)))
    monkeypatch.setattr(code, "handle_lint", lambda paths: records.append(("lint", paths)))
    monkeypatch.setattr(code, "Repo", _FakeRepo)
    monkeypatch.setattr(code, "_current_branch", lambda _project_root: "topic")
    return records


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-2")
@pytest.mark.spec(_SPEC, "UC-CGIP-4")
def test_commit_runs_format_before_lint_and_uses_no_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    (tmp_path / "tracked.py").write_text("print('ok')\n", encoding="utf-8")
    records = _patch_common(
        monkeypatch,
        _scope(DirtyPath("tracked.py", DirtyOp.MODIFIED), DirtyPath("deleted.py", DirtyOp.DELETED)),
    )

    code._commit_under_lock(
        message="test: commit gates",
        includes=[],
        project_root=tmp_path,
        system_role=None,
    )

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-3")
def test_deletion_only_commit_skips_format_and_lint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records = _patch_common(monkeypatch, _scope(DirtyPath("deleted.py", DirtyOp.DELETED)))

    code._commit_under_lock(
        message="test: deletion only",
        includes=[],
        project_root=tmp_path,
        system_role=None,
    )

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-2")
def test_only_commits_declared_subset_of_dirty_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    (tmp_path / "docs.md").write_text("docs\n", encoding="utf-8")
    (tmp_path / "tracked.py").write_text("print('ok')\n", encoding="utf-8")
    records = _patch_common(
        monkeypatch,
        _scope(DirtyPath("docs.md", DirtyOp.MODIFIED), DirtyPath("tracked.py", DirtyOp.MODIFIED)),
    )
    monkeypatch.setattr(code, "get_system_role", lambda: "builder")
    monkeypatch.setattr(code, "resolve_invocation_cwd", lambda: tmp_path)
    monkeypatch.setattr(code, "resolve_git_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(code, "main_branch_lock", nullcontext)

    code.handle_code_commit(["--approved", "test: commit subset", "--only", "docs.md"])

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-1")
def test_malformed_message_blocks_before_format_lint_or_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    records = _patch_common(monkeypatch, _scope(DirtyPath("tracked.py", DirtyOp.MODIFIED)))
    (tmp_path / "tracked.py").write_text("print('ok')\n", encoding="utf-8")

    def fail_message(_message: str, _project_root: Path) -> None:
        records.append("message")
        raise SystemExit(1)

    monkeypatch.setattr(code, "_check_commit_message", fail_message)

    with pytest.raises(SystemExit) as exc:
        code._commit_under_lock(
            message="bad message",
            includes=[],
            project_root=tmp_path,
            system_role=None,
        )

    assert exc.value.code == 1
    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-5")
def test_format_failure_blocks_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tracked.py").write_text("print('ok')\n", encoding="utf-8")
    records = _patch_common(monkeypatch, _scope(DirtyPath("tracked.py", DirtyOp.MODIFIED)))

    def fail_format(_paths: list[str]) -> None:
        records.append("format")
        raise SystemExit(1)

    monkeypatch.setattr(code, "handle_format", fail_format)

    with pytest.raises(SystemExit) as exc:
        code._commit_under_lock(
            message="test: format failure",
            includes=[],
            project_root=tmp_path,
            system_role=None,
        )

    assert exc.value.code == 1
    assert not any(isinstance(record, tuple) and record[0] == "commit" for record in records)


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-6")
def test_lint_failure_blocks_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tracked.py").write_text("print('ok')\n", encoding="utf-8")
    records = _patch_common(monkeypatch, _scope(DirtyPath("tracked.py", DirtyOp.MODIFIED)))

    def fail_lint(_paths: list[str]) -> None:
        records.append("lint")
        raise SystemExit(1)

    monkeypatch.setattr(code, "handle_lint", fail_lint)

    with pytest.raises(SystemExit) as exc:
        code._commit_under_lock(
            message="test: lint failure",
            includes=[],
            project_root=tmp_path,
            system_role=None,
        )

    assert exc.value.code == 1
    assert not any(isinstance(record, tuple) and record[0] == "commit" for record in records)


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-12")
def test_slug_worktree_refuses_doc_layer_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "trees" / "slug-x"
    project_root.mkdir(parents=True)
    records = _patch_common(
        monkeypatch,
        _scope(DirtyPath("docs/feature.md", DirtyOp.MODIFIED)),
    )

    with pytest.raises(SystemExit) as exc:
        code._commit_under_lock(
            message="docs: attempt doc edit in slug worktree",
            includes=[],
            project_root=project_root,
            system_role=None,
        )

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert not any(isinstance(record, tuple) and record[0] in {"format", "lint", "commit"} for record in records)
    assert {"stderr": captured.err} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-13")
def test_shared_branch_commit_is_unaffected_by_doc_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "feature.md").write_text("docs\n", encoding="utf-8")
    scope = WorkspaceScopeResolution(
        kind=WorkspaceScopeKind.SHARED_BRANCH,
        has_session_identity=True,
        dirty_paths=(DirtyPath("docs/feature.md", DirtyOp.MODIFIED),),
        scoped_dirty_paths=("docs/feature.md",),
        scoped_existing_paths=("docs/feature.md",),
    )
    records = _patch_common(monkeypatch, scope)

    code._commit_under_lock(
        message="docs: shared branch doc edit",
        includes=[],
        project_root=tmp_path,
        system_role=None,
    )

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-13")
def test_integration_worktree_commit_is_unaffected_by_doc_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "trees" / "_integration"
    project_root.mkdir(parents=True)
    (project_root / "docs").mkdir()
    (project_root / "docs" / "feature.md").write_text("docs\n", encoding="utf-8")
    records = _patch_common(
        monkeypatch,
        _scope(DirtyPath("docs/feature.md", DirtyOp.MODIFIED)),
    )

    code._commit_under_lock(
        message="docs: integration worktree fold",
        includes=[],
        project_root=project_root,
        system_role=None,
    )

    assert {"records": records} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "path-safety")
def test_commit_rejects_leading_dash_pathspec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch, _scope(DirtyPath("-bad.py", DirtyOp.MODIFIED)))

    with pytest.raises(SystemExit):
        code._commit_under_lock(
            message="test: unsafe path",
            includes=[],
            project_root=tmp_path,
            system_role=None,
        )


def _patch_gate(monkeypatch: pytest.MonkeyPatch, *, branch: str) -> None:
    """Patch the dependencies the un-approved gate path touches before exiting."""
    monkeypatch.setattr(code, "get_system_role", lambda: "builder")
    monkeypatch.setattr(code, "resolve_invocation_cwd", lambda: Path("/repo"))
    monkeypatch.setattr(code, "resolve_git_root", lambda _cwd: Path("/repo"))
    monkeypatch.setattr(code, "_current_branch", lambda _project_root: branch)


def _git(project_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GIT_EXECUTABLE, *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=check,
    )


def _git_stdout(project_root: Path, *args: str) -> str:
    return _git(project_root, *args).stdout.strip()


def _init_conflicting_repo(project_root: Path) -> None:
    _git(project_root, "init", "-b", "topic")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test")
    (project_root / "conflict.txt").write_text("base\n", encoding="utf-8")
    (project_root / "clean.txt").write_text("base\n", encoding="utf-8")
    _git(project_root, "add", "conflict.txt", "clean.txt")
    _git(project_root, "commit", "-m", "seed")
    _git(project_root, "checkout", "-b", "origin/main")
    (project_root / "conflict.txt").write_text("main\n", encoding="utf-8")
    (project_root / "clean.txt").write_text("main\n", encoding="utf-8")
    _git(project_root, "commit", "-am", "main")
    _git(project_root, "checkout", "topic")
    (project_root / "conflict.txt").write_text("topic\n", encoding="utf-8")
    _git(project_root, "commit", "-am", "topic")
    _git(project_root, "merge", "origin/main", check=False)


def _patch_real_commit_boundary(monkeypatch: pytest.MonkeyPatch, project_root: Path) -> list[tuple[str, list[str]]]:
    gate_calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(code, "get_system_role", lambda: "builder")
    monkeypatch.setattr(code, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(code, "resolve_git_root", lambda _cwd: project_root)
    monkeypatch.setattr(code, "main_branch_lock", nullcontext)
    monkeypatch.setattr(code, "_record_commit_checkpoint_markers", lambda _project_root, _committed_files: None)
    monkeypatch.setattr(
        code,
        "resolve_workspace_scope_resolution",
        lambda _project_root: _scope(DirtyPath("conflict.txt", DirtyOp.MODIFIED)),
    )
    monkeypatch.setattr(code, "handle_format", lambda paths: gate_calls.append(("format", paths)))
    monkeypatch.setattr(code, "handle_lint", lambda paths: gate_calls.append(("lint", paths)))
    return gate_calls


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-10")
def test_resolved_merge_commit_records_full_index_merge_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    _init_conflicting_repo(project_root)
    before_head = _git_stdout(project_root, "rev-parse", "HEAD")
    gate_calls = _patch_real_commit_boundary(monkeypatch, project_root)
    (project_root / "conflict.txt").write_text("resolved\n", encoding="utf-8")
    _git(project_root, "add", "conflict.txt")

    code.handle_code_commit(["--approved", "test: merge commit"])

    parents = _git_stdout(project_root, "rev-list", "--parents", "-n1", "HEAD").split()
    assert len(parents) == 3
    assert before_head in parents[1:]
    assert _git_stdout(project_root, "rev-parse", "origin/main") in parents[1:]
    assert {"merged_file": (project_root / "conflict.txt").read_text(encoding="utf-8")} == snapshot
    assert not _git_stdout(project_root, "status", "--porcelain")
    assert gate_calls == [("format", ["clean.txt", "conflict.txt"]), ("lint", ["clean.txt", "conflict.txt"])]


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-11")
def test_unresolved_conflict_aborts_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    _init_conflicting_repo(project_root)
    before_head = _git_stdout(project_root, "rev-parse", "HEAD")
    gate_calls = _patch_real_commit_boundary(monkeypatch, project_root)

    with pytest.raises(SystemExit) as exc:
        code.handle_code_commit(["--approved", "test: unresolved merge"])

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert _git_stdout(project_root, "rev-parse", "HEAD") == before_head
    assert (project_root / ".git" / "MERGE_HEAD").exists()
    assert gate_calls == []
    assert {"stderr": captured.err} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-8")
def test_bare_commit_on_main_surfaces_gate_and_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, branch="main")

    with pytest.raises(SystemExit) as exc:
        code.handle_code_commit([])

    assert exc.value.code == 0


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-8")
def test_bare_commit_off_main_surfaces_help_and_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, branch="topic")

    with pytest.raises(SystemExit) as exc:
        code.handle_code_commit([])

    assert exc.value.code == 0


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-9")
def test_message_without_approved_on_main_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, branch="main")

    with pytest.raises(SystemExit) as exc:
        code.handle_code_commit(["feat(x): y"])

    assert exc.value.code == 1


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "UC-CGIP-9")
def test_message_without_approved_off_main_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gate(monkeypatch, branch="topic")

    with pytest.raises(SystemExit) as exc:
        code.handle_code_commit(["feat(x): y"])

    assert exc.value.code == 2
