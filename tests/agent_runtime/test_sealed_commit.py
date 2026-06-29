"""Functional coverage for sealed commit in-process gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cli.telec.handlers import code
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

    code._commit_under_lock(
        message="test: commit subset",
        includes=[],
        project_root=tmp_path,
        system_role=None,
        only=["docs.md"],
    )

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
