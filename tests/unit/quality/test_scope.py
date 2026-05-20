"""Tests for teleclaude.quality.scope — shared scope utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.project_root import resolve_invocation_cwd, resolve_workspace_root
from teleclaude.quality import scope as scope_module
from teleclaude.quality.scope import (
    CargoWorkspaceError,
    DirtyOp,
    RustScopeKind,
    WorkspaceScopeKind,
    get_project_languages,
    resolve_cargo_workspace_root,
    resolve_rust_scope,
    resolve_workspace_scope_resolution,
    rust_files,
    validate_scoped_paths,
)

PACKAGE_WORKFLOW = "workflow"
PACKAGE_STORAGE = "storage"
WORKFLOW_MEMBER = "workflow_member"
WORKFLOW_SOURCE = "crates/workflow/src/lib.rs"
WORKFLOW_MANIFEST = "crates/workflow/Cargo.toml"
WORKFLOW_MIGRATION = "crates/workflow/migrations/0001_init.sql"
STORAGE_SOURCE = "crates/storage/src/lib.rs"
ROOT_MANIFEST = "Cargo.toml"
ROOT_LOCKFILE = "Cargo.lock"
RUST_TOOLCHAIN = "rust-toolchain.toml"
UNRESOLVED_RUST_SOURCE = "experimental/src/lib.rs"


class _FakeGit:
    def __init__(self, status_output: str) -> None:
        self._status_output = status_output

    def status(self, *args: str) -> str:
        assert args == ("--porcelain", "--untracked-files=all")
        return self._status_output


class _FakeRepo:
    def __init__(self, status_output: str) -> None:
        self.git = _FakeGit(status_output)


def _write_workspace(root: Path) -> None:
    (root / ROOT_MANIFEST).write_text(
        '[workspace]\nmembers = ["crates/workflow", "crates/workflow_member", "crates/storage"]\n',
        encoding="utf-8",
    )


def _write_crate(root: Path, member: str, package: str) -> None:
    crate = root / "crates" / member
    (crate / "src").mkdir(parents=True)
    (crate / "migrations").mkdir()
    (crate / ROOT_MANIFEST).write_text(
        f'[package]\nname = "{package}"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )


class TestResolveWorkspaceRoot:
    """resolve_workspace_root walks up to find teleclaude.yml."""

    def test_finds_root_with_teleclaude_yml(self, tmp_path: Path) -> None:
        """Returns the directory containing teleclaude.yml."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)

        assert resolve_workspace_root(sub) == tmp_path


class TestValidateScopedPaths:
    """validate_scoped_paths filters out dangerous paths."""

    def test_filters_traversal_paths(self, tmp_path: Path) -> None:
        """Paths containing '..' are rejected."""
        result = validate_scoped_paths(["../etc/passwd", "ok.py"], tmp_path)
        assert result == ["ok.py"]

    def test_filters_absolute_paths_outside_root(self, tmp_path: Path) -> None:
        """Absolute paths outside project root are rejected."""
        result = validate_scoped_paths(["/etc/passwd", "ok.py"], tmp_path)
        assert result == ["ok.py"]


class TestResolveWorkspaceScopeResolution:
    """Workspace scope resolution owns dirty metadata and scoped path selection."""

    def test_worktree_scope_uses_dirty_existing_paths_and_classifies_operations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "teleclaude").mkdir()
        (tmp_path / "teleclaude" / "changed.py").write_text("print('changed')\n", encoding="utf-8")
        (tmp_path / "teleclaude" / "new.py").write_text("print('new')\n", encoding="utf-8")
        status_output = "\n".join(
            [
                " M teleclaude/changed.py",
                "?? teleclaude/new.py",
                " D teleclaude/gone.py",
            ]
        )

        monkeypatch.setattr(scope_module, "is_worktree", lambda _path: True)
        monkeypatch.setattr(scope_module, "get_session_id", lambda: None)
        monkeypatch.setattr(scope_module, "Repo", lambda _root: _FakeRepo(status_output))

        resolution = resolve_workspace_scope_resolution(tmp_path)

        assert resolution.kind is WorkspaceScopeKind.WORKTREE
        assert resolution.has_session_identity is False
        assert resolution.scoped_dirty_paths == (
            "teleclaude/changed.py",
            "teleclaude/new.py",
            "teleclaude/gone.py",
        )
        assert resolution.scoped_existing_paths == ("teleclaude/changed.py", "teleclaude/new.py")
        assert {(dirty.path, dirty.op) for dirty in resolution.dirty_paths} == {
            ("teleclaude/changed.py", DirtyOp.MODIFIED),
            ("teleclaude/new.py", DirtyOp.ADDED),
            ("teleclaude/gone.py", DirtyOp.DELETED),
        }

    def test_shared_branch_with_session_scopes_to_session_touched_dirty_existing_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "teleclaude").mkdir()
        (tmp_path / "teleclaude" / "touched.py").write_text("print('touched')\n", encoding="utf-8")
        (tmp_path / "teleclaude" / "other.py").write_text("print('other')\n", encoding="utf-8")
        (tmp_path / "teleclaude" / "new.py").write_text("print('new')\n", encoding="utf-8")
        status_output = "\n".join(
            [
                " M teleclaude/touched.py",
                " M teleclaude/other.py",
                "?? teleclaude/new.py",
                " D teleclaude/gone.py",
            ]
        )

        monkeypatch.setattr(scope_module, "is_worktree", lambda _path: False)
        monkeypatch.setattr(scope_module, "get_session_id", lambda: "sess-123")
        monkeypatch.setattr(
            scope_module,
            "collect_session_touched_files",
            lambda _root: {"teleclaude/touched.py", "teleclaude/new.py", "teleclaude/gone.py"},
        )
        monkeypatch.setattr(scope_module, "Repo", lambda _root: _FakeRepo(status_output))

        resolution = resolve_workspace_scope_resolution(tmp_path)

        assert resolution.kind is WorkspaceScopeKind.SHARED_BRANCH
        assert resolution.has_session_identity is True
        assert resolution.scoped_dirty_paths == (
            "teleclaude/gone.py",
            "teleclaude/new.py",
            "teleclaude/touched.py",
        )
        assert resolution.scoped_existing_paths == ("teleclaude/new.py", "teleclaude/touched.py")

    def test_shared_branch_excludes_pending_deletions_outside_session_touched_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deleted file the session did NOT touch must NOT enter scope.

        The previous implementation unioned ALL dirty-deleted paths into
        scope (justified by "Bash-rm fell out of transcript-touched signal"),
        but the side-effect was a cross-session leak: agent A deletes foo.py,
        agent B's scope picks up that deletion, and B's commit silently
        records A's work. New invariant: scope is strictly
        (this session's touched paths) ∩ (currently dirty paths). A
        Bash-`rm` deletion that the transcript extractor missed must be
        declared explicitly by the agent with
        `telec code commit --approved '<msg>' --include <deleted-path>`.
        """
        (tmp_path / "teleclaude").mkdir()
        (tmp_path / "teleclaude" / "kept.py").write_text("print('kept')\n", encoding="utf-8")
        status_output = "\n".join(
            [
                " M teleclaude/kept.py",
                " D teleclaude/removed_via_bash.py",
            ]
        )

        monkeypatch.setattr(scope_module, "is_worktree", lambda _path: False)
        monkeypatch.setattr(scope_module, "get_session_id", lambda: "sess-456")
        monkeypatch.setattr(
            scope_module,
            "collect_session_touched_files",
            lambda _root: {"teleclaude/kept.py"},
        )
        monkeypatch.setattr(scope_module, "Repo", lambda _root: _FakeRepo(status_output))

        resolution = resolve_workspace_scope_resolution(tmp_path)

        assert resolution.kind is WorkspaceScopeKind.SHARED_BRANCH
        # Scope excludes the untouched deletion.
        assert resolution.scoped_dirty_paths == ("teleclaude/kept.py",)
        assert resolution.scoped_existing_paths == ("teleclaude/kept.py",)
        # Raw dirty paths still report both — the working-tree state is
        # unchanged; only the SCOPED subset is filtered.
        dirty = {d.path for d in resolution.dirty_paths}
        assert dirty == {"teleclaude/kept.py", "teleclaude/removed_via_bash.py"}

    def test_shared_branch_without_session_keeps_dirty_metadata_but_returns_empty_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "teleclaude").mkdir()
        (tmp_path / "teleclaude" / "changed.py").write_text("print('changed')\n", encoding="utf-8")
        status_output = " M teleclaude/changed.py"

        monkeypatch.setattr(scope_module, "is_worktree", lambda _path: False)
        monkeypatch.setattr(scope_module, "get_session_id", lambda: None)
        monkeypatch.setattr(scope_module, "Repo", lambda _root: _FakeRepo(status_output))

        resolution = resolve_workspace_scope_resolution(tmp_path)

        assert resolution.kind is WorkspaceScopeKind.SHARED_BRANCH
        assert resolution.has_session_identity is False
        assert resolution.dirty_paths == (scope_module.DirtyPath("teleclaude/changed.py", DirtyOp.MODIFIED),)
        assert resolution.scoped_dirty_paths == ()
        assert resolution.scoped_existing_paths == ()


class TestGetProjectLanguages:
    """get_project_languages reads the languages list from teleclaude.yml."""

    def test_returns_languages_list_from_config(self, tmp_path: Path) -> None:
        """Reads the languages list when present."""
        (tmp_path / "teleclaude.yml").write_text("languages:\n  - python\n  - typescript\n", encoding="utf-8")

        assert get_project_languages(tmp_path) == ["python", "typescript"]

    def test_falls_back_to_singular_language_field(self, tmp_path: Path) -> None:
        """Backward compat: wraps singular language in a list."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        assert get_project_languages(tmp_path) == ["python"]

    def test_prefers_languages_over_language(self, tmp_path: Path) -> None:
        """When both fields exist, languages takes precedence."""
        (tmp_path / "teleclaude.yml").write_text("language: python\nlanguages:\n  - typescript\n", encoding="utf-8")

        assert get_project_languages(tmp_path) == ["typescript"]

    def test_returns_empty_list_when_no_language_fields(self, tmp_path: Path) -> None:
        """Returns empty list when neither field exists."""
        (tmp_path / "teleclaude.yml").write_text("business:\n  domains: {}\n", encoding="utf-8")

        assert get_project_languages(tmp_path) == []

    def test_returns_empty_list_when_no_config_file(self, tmp_path: Path) -> None:
        """Returns empty list when teleclaude.yml doesn't exist."""
        assert get_project_languages(tmp_path) == []


class TestRustFiles:
    """Rust-owned path filtering follows the Cargo workspace contract."""

    def test_rust_files_returns_only_rust_owned_paths(self) -> None:
        """The documented Rust path set is retained and unrelated files are dropped."""
        paths = [
            WORKFLOW_SOURCE,
            WORKFLOW_MANIFEST,
            WORKFLOW_MIGRATION,
            ROOT_MANIFEST,
            ROOT_LOCKFILE,
            RUST_TOOLCHAIN,
            "teleclaude/quality/lint.py",
            "docs/x.md",
        ]

        assert rust_files(paths) == [
            WORKFLOW_SOURCE,
            WORKFLOW_MANIFEST,
            WORKFLOW_MIGRATION,
            ROOT_MANIFEST,
            ROOT_LOCKFILE,
            RUST_TOOLCHAIN,
        ]


class TestResolveCargoWorkspaceRoot:
    """Cargo workspace root resolution is anchored by root Cargo.toml."""

    def test_resolves_workspace_root_to_root_manifest_parent(self, tmp_path: Path) -> None:
        """The workspace root is the parent directory of root Cargo.toml."""
        _write_workspace(tmp_path)

        assert resolve_cargo_workspace_root(tmp_path) == tmp_path

    def test_missing_workspace_manifest_raises_specific_error(self, tmp_path: Path) -> None:
        """A Rust project without root Cargo.toml fails fast."""
        with pytest.raises(CargoWorkspaceError) as exc_info:
            resolve_cargo_workspace_root(tmp_path)

        assert exc_info.value.manifest_path == tmp_path / ROOT_MANIFEST


class TestResolveRustScope:
    """Rust scope resolution maps changed files to Cargo package/workspace scope."""

    def test_crate_path_maps_to_package_name_from_manifest(self, tmp_path: Path) -> None:
        """Package names come from crate Cargo.toml, not member directory names."""
        _write_workspace(tmp_path)
        _write_crate(tmp_path, WORKFLOW_MEMBER, PACKAGE_WORKFLOW)

        resolved = resolve_rust_scope(tmp_path, [f"crates/{WORKFLOW_MEMBER}/src/lib.rs"])

        assert resolved.kind is RustScopeKind.PACKAGE
        assert resolved.package == PACKAGE_WORKFLOW

    def test_single_crate_paths_resolve_to_package_scope(self, tmp_path: Path) -> None:
        """All Rust-owned paths in one crate produce single-package scope."""
        _write_workspace(tmp_path)
        _write_crate(tmp_path, "workflow", PACKAGE_WORKFLOW)

        resolved = resolve_rust_scope(
            tmp_path,
            [
                "crates/workflow/src/a.rs",
                "crates/workflow/src/b.rs",
                WORKFLOW_MIGRATION,
            ],
        )

        assert resolved.kind is RustScopeKind.PACKAGE
        assert resolved.package == PACKAGE_WORKFLOW

    def test_cross_crate_paths_resolve_to_workspace_scope(self, tmp_path: Path) -> None:
        """Rust-owned paths spanning crates produce workspace scope."""
        _write_workspace(tmp_path)
        _write_crate(tmp_path, "workflow", PACKAGE_WORKFLOW)
        _write_crate(tmp_path, "storage", PACKAGE_STORAGE)

        resolved = resolve_rust_scope(tmp_path, [WORKFLOW_SOURCE, STORAGE_SOURCE])

        assert resolved.kind is RustScopeKind.WORKSPACE
        assert resolved.package is None

    def test_root_manifest_change_forces_workspace_scope(self, tmp_path: Path) -> None:
        """Root Cargo.toml is a workspace-wide trigger."""
        _write_workspace(tmp_path)

        resolved = resolve_rust_scope(tmp_path, [ROOT_MANIFEST])

        assert resolved.kind is RustScopeKind.WORKSPACE

    def test_root_lockfile_change_forces_workspace_scope(self, tmp_path: Path) -> None:
        """Root Cargo.lock is a workspace-wide trigger."""
        _write_workspace(tmp_path)

        resolved = resolve_rust_scope(tmp_path, [ROOT_LOCKFILE])

        assert resolved.kind is RustScopeKind.WORKSPACE

    def test_rust_toolchain_change_forces_workspace_scope(self, tmp_path: Path) -> None:
        """rust-toolchain.toml is a workspace-wide trigger."""
        _write_workspace(tmp_path)

        resolved = resolve_rust_scope(tmp_path, [RUST_TOOLCHAIN])

        assert resolved.kind is RustScopeKind.WORKSPACE

    def test_run_all_forces_workspace_scope(self, tmp_path: Path) -> None:
        """--all overrides package-local changed-file scope."""
        _write_workspace(tmp_path)
        _write_crate(tmp_path, "workflow", PACKAGE_WORKFLOW)

        resolved = resolve_rust_scope(tmp_path, [WORKFLOW_SOURCE], run_all=True)

        assert resolved.kind is RustScopeKind.WORKSPACE
        assert resolved.package is None

    def test_unresolvable_ownership_downgrades_to_workspace_scope(self, tmp_path: Path) -> None:
        """Rust-owned paths outside crates/ are tracked as unresolved workspace scope."""
        _write_workspace(tmp_path)

        resolved = resolve_rust_scope(tmp_path, [UNRESOLVED_RUST_SOURCE])

        assert resolved.kind is RustScopeKind.WORKSPACE
        assert resolved.unresolved_paths == (UNRESOLVED_RUST_SOURCE,)

    def test_no_rust_owned_paths_returns_empty_scope_without_workspace_manifest(self, tmp_path: Path) -> None:
        """Non-Rust paths do not require a Cargo workspace."""
        resolved = resolve_rust_scope(tmp_path, ["teleclaude/quality/lint.py", "docs/x.md"])

        assert resolved.kind is RustScopeKind.EMPTY
        assert resolved.workspace_root is None

    def test_sql_migration_under_crate_maps_to_package_scope(self, tmp_path: Path) -> None:
        """SQL migrations under a crate trigger that crate's cargo scope."""
        _write_workspace(tmp_path)
        _write_crate(tmp_path, "workflow", PACKAGE_WORKFLOW)

        resolved = resolve_rust_scope(tmp_path, [WORKFLOW_MIGRATION])

        assert resolved.kind is RustScopeKind.PACKAGE
        assert resolved.package == PACKAGE_WORKFLOW


class TestResolveInvocationCwd:
    """resolve_invocation_cwd returns the user's actual invocation directory.

    R1 regression guard: the bin/telec wrapper uses `uv run --directory` which
    sets the Python process cwd to TeleClaude's install root. `Path.cwd()`
    then no longer reflects the directory the user was in. Handlers must use
    this helper (not `Path.cwd()`) so worktree scoping survives the wrapper.
    """

    def test_prefers_telec_env_var_over_pwd_and_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TELEC_INVOCATION_CWD wins over PWD and Path.cwd()."""
        invocation = tmp_path / "worktree"
        invocation.mkdir()
        wrong_pwd = tmp_path / "shell_pwd"
        wrong_pwd.mkdir()
        wrong_cwd = tmp_path / "process_cwd"
        wrong_cwd.mkdir()

        monkeypatch.setenv("TELEC_INVOCATION_CWD", str(invocation))
        monkeypatch.setenv("PWD", str(wrong_pwd))
        monkeypatch.chdir(wrong_cwd)

        assert resolve_invocation_cwd() == invocation

    def test_falls_back_to_pwd_when_telec_env_var_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PWD wins over Path.cwd() when TELEC_INVOCATION_CWD is unset."""
        invocation = tmp_path / "worktree"
        invocation.mkdir()
        wrong_cwd = tmp_path / "process_cwd"
        wrong_cwd.mkdir()

        monkeypatch.delenv("TELEC_INVOCATION_CWD", raising=False)
        monkeypatch.setenv("PWD", str(invocation))
        monkeypatch.chdir(wrong_cwd)

        assert resolve_invocation_cwd() == invocation

    def test_falls_back_to_path_cwd_when_env_vars_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path.cwd() is the last resort when no env var is set."""
        monkeypatch.delenv("TELEC_INVOCATION_CWD", raising=False)
        monkeypatch.delenv("PWD", raising=False)
        monkeypatch.chdir(tmp_path)

        assert resolve_invocation_cwd() == tmp_path

    def test_wrapper_simulated_worktree_invocation_resolves_to_worktree_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R1: simulating bin/telec's --directory hijack, project root resolves to the worktree.

        Quoted from R1 requirement: 'If session scope resolution fails in a
        worktree, the command must exit non-zero — never silently fall back
        to repo-wide execution.' The failure mode this test guards: the
        wrapper sets process cwd to the main repo, handler sees main's
        teleclaude.yml, is_worktree returns False, lint scans the whole repo
        silently. Using the invocation cwd instead of Path.cwd() prevents
        this.
        """
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        (main_repo / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        worktree = main_repo / "trees" / "feature"
        worktree.mkdir(parents=True)
        (worktree / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        # Simulate the wrapper: user ran `telec code lint` from the worktree, but
        # uv run --directory changed Python's cwd to main_repo.
        monkeypatch.chdir(main_repo)
        monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))

        resolved = resolve_workspace_root(resolve_invocation_cwd())
        assert resolved == worktree, (
            f"Expected worktree {worktree}, got {resolved}. The wrapper-cwd hijack bypassed invocation-cwd resolution."
        )
