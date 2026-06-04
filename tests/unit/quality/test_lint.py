"""Tests for R1: telec code lint command.

Behavioral contracts for the telec code lint command: language-aware lint pipeline
with automatic worktree scoping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.project_root import resolve_workspace_root
from teleclaude.quality.lint import (
    LintRunner,
    PythonLintPipeline,
    TypeScriptLintPipeline,
    get_project_languages,
)
from teleclaude.quality.scope import DirtyOp, DirtyPath, WorkspaceScopeKind, WorkspaceScopeResolution

PACKAGE_STORAGE = "storage"
PACKAGE_WORKFLOW = "workflow"
WORKFLOW_SOURCE = "crates/workflow/src/lib.rs"
STORAGE_SOURCE = "crates/storage/src/lib.rs"
PYTHON_SOURCE = "teleclaude/foo.py"
TYPESCRIPT_SOURCE = "frontend/app/foo.tsx"

_STEP_MARKDOWN = "markdown"
_STEP_RESOURCE_VALIDATION = "resource_validation"
_STEP_ESLINT = "eslint"
_STEP_TSC = "tsc"
_TS_RELATIVE_PATH = "app/foo.tsx"
_PY_SUFFIX = ".py"


def _workspace_resolution(
    *,
    kind: WorkspaceScopeKind,
    scoped_existing_paths: tuple[str, ...],
    has_session_identity: bool = True,
) -> WorkspaceScopeResolution:
    return WorkspaceScopeResolution(
        kind=kind,
        has_session_identity=has_session_identity,
        dirty_paths=tuple(DirtyPath(path, DirtyOp.MODIFIED) for path in scoped_existing_paths),
        scoped_dirty_paths=scoped_existing_paths,
        scoped_existing_paths=scoped_existing_paths,
    )


def _write_rust_workspace(root: Path) -> None:
    (root / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/workflow", "crates/storage"]\n',
        encoding="utf-8",
    )
    _write_rust_crate(root, "workflow", PACKAGE_WORKFLOW)
    _write_rust_crate(root, "storage", PACKAGE_STORAGE)


def _write_rust_crate(root: Path, member: str, package: str) -> None:
    crate = root / "crates" / member
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        f'[package]\nname = "{package}"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# R1.1 — Project root resolution from cwd
# ---------------------------------------------------------------------------


class TestProjectRootResolution:
    """The lint command resolves the project root from the current directory."""

    def test_resolves_root_by_teleclaude_yml_presence(self, tmp_path: Path) -> None:
        """Project root is the nearest ancestor directory containing teleclaude.yml."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        sub = tmp_path / "subdir" / "nested"
        sub.mkdir(parents=True)

        resolved = resolve_workspace_root(sub)
        assert resolved == tmp_path

    def test_raises_when_no_teleclaude_yml_found(self, tmp_path: Path) -> None:
        """Resolution raises an error when no teleclaude.yml is found in the hierarchy."""
        with pytest.raises((FileNotFoundError, RuntimeError, SystemExit)):
            resolve_workspace_root(tmp_path)


# ---------------------------------------------------------------------------
# R1.2 — Language detection from teleclaude.yml
# ---------------------------------------------------------------------------


class TestLanguageDetection:
    """Languages are detected from filesystem artifacts."""

    def test_reads_python_language_from_pyproject_toml(self, tmp_path: Path) -> None:
        """pyproject.toml presence returns ['python'] as the project languages."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")

        langs = get_project_languages(tmp_path)
        assert langs == ["python"]

    def test_no_language_field_returns_empty_list(self, tmp_path: Path) -> None:
        """No recognised artifacts returns empty list."""
        (tmp_path / "teleclaude.yml").write_text("business:\n  domains: {}\n", encoding="utf-8")

        langs = get_project_languages(tmp_path)
        assert langs == []


# ---------------------------------------------------------------------------
# R1.3 — Shared branch scope failure exits non-zero (no silent fallback)
# ---------------------------------------------------------------------------


class TestSharedBranchScopeFailure:
    """On a shared branch with session identity, scope failure must exit non-zero."""

    def test_scope_failure_on_shared_branch_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When scope resolution fails on a shared branch with a session, the command exits non-zero."""

        def _fail_scope(_path: Path) -> WorkspaceScopeResolution:
            raise RuntimeError("transcript unavailable")

        monkeypatch.setattr("teleclaude.quality.lint.resolve_workspace_scope_resolution", _fail_scope)

        runner = LintRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run()
        assert exc_info.value.code != 0

    def test_scope_failure_does_not_silently_fall_back_to_repo_wide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scope failure on shared branch must never silently run against all source dirs."""
        pipeline_calls: list[object] = []

        def _fail_scope(_path: Path) -> WorkspaceScopeResolution:
            raise RuntimeError("transcript unavailable")

        monkeypatch.setattr("teleclaude.quality.lint.resolve_workspace_scope_resolution", _fail_scope)
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            pipeline_calls.append,
        )

        runner = LintRunner(project_root=tmp_path)
        try:
            runner.run()
        except SystemExit:
            pass
        assert not pipeline_calls, "Pipeline ran after scope failure ��� silent fallback is forbidden"


# ---------------------------------------------------------------------------
# R1.4 — Worktree context runs against source directories
# ---------------------------------------------------------------------------


class TestWorktreeContext:
    """In a worktree, lint targets dirty existing files from the resolver."""

    def test_worktree_receives_resolved_dirty_existing_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("teleclaude/foo.py", "tests/unit/test_foo.py"),
            ),
        )
        monkeypatch.setattr("teleclaude.quality.lint.run_pipeline", received_targets.append)

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert received_targets == [["teleclaude/foo.py", "tests/unit/test_foo.py"]]

    def test_worktree_receives_file_targets_not_source_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("teleclaude/foo.py",),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1
        targets_arg = received_targets[0]
        assert targets_arg, "Pipeline received empty targets in worktree mode"
        if hasattr(targets_arg, "__iter__") and not isinstance(targets_arg, str):
            items = list(targets_arg)  # pyright: ignore[reportUnknownArgumentType]
            assert items == ["teleclaude/foo.py"]


# ---------------------------------------------------------------------------
# R1.4b — Multi-language collects dirs from all toolchains
# ---------------------------------------------------------------------------


class TestMultiLanguageSourceDirs:
    """Multi-language config collects source dirs from all registered toolchains."""

    def test_multi_language_collects_dirs_from_all_registered_toolchains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When languages list has multiple entries, source dirs from all registered toolchains are collected."""
        received_targets: list[object] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=(),
                has_session_identity=False,
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.get_project_languages",
            lambda _path: ["python"],
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1
        targets_arg = received_targets[0]
        assert targets_arg, "Pipeline received empty targets"

    def test_unregistered_language_skipped_gracefully(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Languages without a registered toolchain are skipped, not errored."""
        received_targets: list[object] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=(),
                has_session_identity=False,
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.get_project_languages",
            lambda _path: ["python", "cobol"],
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1, "Pipeline should still run for registered languages"


# ---------------------------------------------------------------------------
# R1.5 — Shared branch with session scopes to session-touched files
# ---------------------------------------------------------------------------


class TestSharedBranchScopeSuccess:
    """On a shared branch with a session, the pipeline receives session-scoped files."""

    def test_shared_branch_with_session_passes_scoped_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session scope resolves successfully on shared branch — pipeline gets scoped file list."""
        scoped_files = ["teleclaude/foo/bar.py", "teleclaude/baz/qux.py"]
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=tuple(scoped_files),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1, "Pipeline was not called exactly once"
        targets_arg = received_targets[0]
        if hasattr(targets_arg, "__iter__") and not isinstance(targets_arg, str):
            items = list(targets_arg)  # pyright: ignore[reportUnknownArgumentType]
            assert all(str(t).endswith(_PY_SUFFIX) for t in items), (
                f"Shared branch pipeline received non-file targets — expected scoped .py files: {items}"
            )
            assert set(str(t) for t in items) == set(scoped_files), (
                f"Pipeline received wrong file set: {items} vs {scoped_files}"
            )

    def test_no_session_identity_falls_back_to_source_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without session identity on shared branch, pipeline runs against source dirs."""
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=(),
                has_session_identity=False,
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1
        targets_arg = received_targets[0]
        assert targets_arg, "Pipeline received empty targets without session identity"


# ---------------------------------------------------------------------------
# R1.6 — Explicit files bypass scoping
# ---------------------------------------------------------------------------


class TestExplicitFilesOverride:
    """When explicit files are passed, all scoping is bypassed."""

    def test_explicit_files_bypass_scoping(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit file arguments go directly to the pipeline without scoping."""
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run(files=["teleclaude/foo.py", "teleclaude/bar.py"])

        assert len(received_targets) == 1
        targets_arg = received_targets[0]
        if hasattr(targets_arg, "__iter__") and not isinstance(targets_arg, str):
            items = list(targets_arg)  # pyright: ignore[reportUnknownArgumentType]
            assert set(str(t) for t in items) == {"teleclaude/foo.py", "teleclaude/bar.py"}

    def test_explicit_yaml_files_skip_python_steps(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit YAML files run repo-global checks only, not Python-specific steps."""
        step_calls: list[tuple[str, list[str]]] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint.get_project_languages",
            lambda _path: ["python", "typescript"],
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: step_calls.append((step_name, list(cmd))),
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run(files=[".github/workflows/lint-test.yaml"])

        step_names = [name for name, _cmd in step_calls]
        assert _STEP_MARKDOWN in step_names
        assert _STEP_RESOURCE_VALIDATION in step_names
        assert "ruff_check" not in step_names
        assert "ruff_format" not in step_names
        assert "pyright" not in step_names
        assert "mypy" not in step_names
        assert "jscpd" not in step_names
        assert "eslint" not in step_names
        assert "tsc" not in step_names

    def test_explicit_typescript_files_run_typescript_steps_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit TS files dispatch to frontend lint steps without Python fallback."""
        step_calls: list[tuple[str, str, list[str]]] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint.get_project_languages",
            lambda _path: ["python", "typescript"],
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: step_calls.append((step_name, str(cwd), list(cmd))),
        )

        (tmp_path / "teleclaude.yml").write_text(
            "languages:\n  - python\n  - typescript\nfrontend_root: frontend\n",
            encoding="utf-8",
        )
        (tmp_path / "frontend").mkdir()

        runner = LintRunner(project_root=tmp_path)
        runner.run(files=["frontend/app/foo.tsx"])

        step_names = [name for name, _cwd, _cmd in step_calls]
        assert _STEP_ESLINT in step_names
        assert _STEP_TSC in step_names
        assert "ruff_check" not in step_names
        assert "ruff_format" not in step_names
        assert "pyright" not in step_names
        assert "mypy" not in step_names
        assert "jscpd" not in step_names

        eslint_call = next((entry for entry in step_calls if entry[0] == _STEP_ESLINT), None)
        assert eslint_call is not None
        _, cwd, cmd = eslint_call
        assert cwd == str(tmp_path / "frontend")
        assert _TS_RELATIVE_PATH in cmd


# ---------------------------------------------------------------------------
# R1.7 — Python pipeline deterministic order
# ---------------------------------------------------------------------------


class TestPythonPipelineOrder:
    """The Python lint pipeline runs in a deterministic, required order."""

    def test_pipeline_steps_run_in_required_order(self, tmp_path: Path) -> None:
        """Pipeline order: guardrails, markdown, resource_validation, ruff, pyright, mypy, jscpd."""
        pipeline = PythonLintPipeline(project_root=tmp_path)
        step_names = [step.name for step in pipeline.steps]

        required_order = [
            "guardrails",
            "markdown",
            "resource_validation",
            "ruff_check",
            "ruff_format",
            "pyright",
            "mypy",
            "jscpd",
        ]
        for required in required_order:
            matching = [name for name in step_names if required in name.lower()]
            assert len(matching) >= 1, f"Required step '{required}' not found in pipeline steps: {step_names}"

        # Verify relative ordering of key pairs
        positions = {
            required: next(i for i, name in enumerate(step_names) if required in name.lower())
            for required in required_order
        }
        assert positions["guardrails"] < positions["markdown"], "guardrails must run before markdown"
        assert positions["markdown"] < positions["resource_validation"], "markdown must run before resource_validation"
        assert positions["resource_validation"] < positions["ruff_check"], (
            "resource_validation must run before ruff_check"
        )
        assert positions["ruff_check"] < positions["ruff_format"], "ruff_check must run before ruff_format"
        assert positions["ruff_format"] < positions["pyright"], "ruff_format must run before pyright"
        assert positions["pyright"] < positions["jscpd"], "pyright must run before jscpd"
        assert positions["mypy"] < positions["jscpd"], "mypy must run before jscpd"

    def test_pyright_step_uses_uv_invocation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pyright runs through the uv-managed project environment."""
        calls: list[tuple[list[str], Path, str]] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: calls.append((list(cmd), cwd, step_name)),
        )

        pipeline = PythonLintPipeline(project_root=tmp_path)
        pyright_step = next(step for step in pipeline.steps if step.name == "pyright")
        pyright_step.run(["teleclaude/foo.py"])

        assert calls == [(["uv", "run", "pyright", "teleclaude/foo.py"], tmp_path, "pyright")]

    def test_mypy_step_uses_uv_invocation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mypy runs through the uv-managed project environment."""
        calls: list[tuple[list[str], Path, str]] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: calls.append((list(cmd), cwd, step_name)),
        )

        pipeline = PythonLintPipeline(project_root=tmp_path)
        mypy_step = next(step for step in pipeline.steps if step.name == "mypy")
        mypy_step.run(["teleclaude/foo.py"])

        assert calls == [(["uv", "run", "mypy", "teleclaude/foo.py"], tmp_path, "mypy")]


# ---------------------------------------------------------------------------
# TypeScript lint pipeline
# ---------------------------------------------------------------------------


class TestTypeScriptLintPipeline:
    """TypeScript lint pipeline has eslint and tsc steps."""

    def test_typescript_pipeline_has_eslint_and_tsc(self, tmp_path: Path) -> None:
        """TypeScript pipeline contains eslint and tsc steps."""
        pipeline = TypeScriptLintPipeline(tmp_path, tmp_path / "frontend")
        step_names = [step.name for step in pipeline.steps]
        assert _STEP_ESLINT in step_names, f"{_STEP_ESLINT!r} not found in TS pipeline: {step_names}"
        assert _STEP_TSC in step_names, f"{_STEP_TSC!r} not found in TS pipeline: {step_names}"

    def test_typescript_pipeline_eslint_before_tsc(self, tmp_path: Path) -> None:
        """eslint runs before tsc in the TypeScript pipeline."""
        pipeline = TypeScriptLintPipeline(tmp_path, tmp_path / "frontend")
        step_names = [step.name for step in pipeline.steps]
        assert step_names.index(_STEP_ESLINT) < step_names.index(_STEP_TSC), "eslint must run before tsc"


# ---------------------------------------------------------------------------
# Multi-language lint dispatch runs both pipelines
# ---------------------------------------------------------------------------


class TestMultiLanguageLintDispatch:
    """LintRunner.run() dispatches both Python and TypeScript lint pipelines."""

    def test_run_dispatches_typescript_pipeline_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LintRunner.run() runs TypeScript pipeline when typescript is in languages."""
        python_calls: list[object] = []
        ts_step_calls: list[tuple[str, list[str]]] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("teleclaude/foo.py", "frontend/app/foo.tsx"),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.get_project_languages",
            lambda _path: ["python", "typescript"],
        )
        monkeypatch.setattr("teleclaude.quality.lint.run_pipeline", python_calls.append)

        def _capture_run_tool(cmd: list[str], cwd: Path, step_name: str) -> None:
            if step_name in ("eslint", "tsc"):
                ts_step_calls.append((step_name, list(cmd)))

        monkeypatch.setattr("teleclaude.quality.lint._run_tool", _capture_run_tool)

        (tmp_path / "teleclaude.yml").write_text(
            "languages:\n  - python\n  - typescript\nfrontend_root: frontend\n",
            encoding="utf-8",
        )
        frontend = tmp_path / "frontend"
        frontend.mkdir()

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(python_calls) >= 1, "Python pipeline was not called"
        ts_step_names = [name for name, _ in ts_step_calls]
        assert _STEP_ESLINT in ts_step_names, (
            f"{_STEP_ESLINT!r} was not dispatched — TS pipeline not running: {ts_step_calls}"
        )
        assert _STEP_TSC in ts_step_names, (
            f"{_STEP_TSC!r} was not dispatched — TS pipeline not running: {ts_step_calls}"
        )

    def test_typescript_steps_run_from_frontend_root_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TypeScript lint steps (eslint, tsc) execute from the frontend_root directory as cwd."""
        cwd_captures: list[tuple[str, str]] = []

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("myfrontend/app/foo.tsx",),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.get_project_languages",
            lambda _path: ["python", "typescript"],
        )
        monkeypatch.setattr("teleclaude.quality.lint.run_pipeline", lambda _targets: None)

        def _capture_cwd(cmd: list[str], cwd: Path, step_name: str) -> None:
            cwd_captures.append((step_name, str(cwd)))

        monkeypatch.setattr("teleclaude.quality.lint._run_tool", _capture_cwd)

        (tmp_path / "teleclaude.yml").write_text(
            "languages:\n  - python\n  - typescript\nfrontend_root: myfrontend\n",
            encoding="utf-8",
        )
        (tmp_path / "myfrontend").mkdir()

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        eslint_cwds = [cwd for name, cwd in cwd_captures if name == "eslint"]
        assert len(eslint_cwds) >= 1, "eslint was not invoked"
        expected_cwd = str(tmp_path / "myfrontend")
        assert eslint_cwds[0] == expected_cwd, f"eslint ran from {eslint_cwds[0]!r}, expected {expected_cwd!r}"

    def test_eslint_not_in_python_pipeline(self, tmp_path: Path) -> None:
        """eslint is not a step in the Python lint pipeline."""
        pipeline = PythonLintPipeline(project_root=tmp_path)
        py_step_names = [s.name for s in pipeline.steps]
        assert "eslint" not in py_step_names


class TestRustLintDispatch:
    """LintRunner dispatches Cargo linting only for declared Rust projects."""

    def test_rust_only_project_skips_python_pipeline_and_runs_cargo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rust-only lint runs cargo without entering the Python pipeline."""
        _write_rust_workspace(tmp_path)
        python_calls: list[object] = []
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE,),
            ),
        )
        monkeypatch.setattr("teleclaude.quality.lint.run_pipeline", python_calls.append)
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run()

        assert python_calls == []
        assert [name for name, _cmd, _cwd in tool_calls] == ["cargo_fmt_check", "cargo_clippy"]

    def test_mixed_python_and_rust_project_runs_both_pipelines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mixed projects lint Python targets and Cargo scope in one runner call."""
        _write_rust_workspace(tmp_path)
        python_calls: list[object] = []
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python", "rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(PYTHON_SOURCE, WORKFLOW_SOURCE),
            ),
        )
        monkeypatch.setattr("teleclaude.quality.lint.run_pipeline", python_calls.append)
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run()

        assert python_calls == [[PYTHON_SOURCE, WORKFLOW_SOURCE]]
        assert [name for name, _cmd, _cwd in tool_calls] == ["cargo_fmt_check", "cargo_clippy"]

    def test_python_only_project_never_invokes_cargo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rust-looking paths are ignored when rust is not declared."""
        python_calls: list[object] = []
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(PYTHON_SOURCE, WORKFLOW_SOURCE),
            ),
        )
        monkeypatch.setattr("teleclaude.quality.lint.run_pipeline", python_calls.append)
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run()

        assert python_calls == [[PYTHON_SOURCE, WORKFLOW_SOURCE]]
        assert [call for call in tool_calls if call[1] and call[1][0] == "cargo"] == []

    def test_rust_lint_empty_file_scope_skips_cargo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Declared Rust with no Rust-owned paths does not launch cargo."""
        _write_rust_workspace(tmp_path)
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("docs/x.md",),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run()

        assert tool_calls == []

    def test_single_package_scope_uses_package_cargo_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single-crate Rust scope maps to cargo -p commands from workspace root."""
        _write_rust_workspace(tmp_path)
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE,),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run()

        assert tool_calls == [
            ("cargo_fmt_check", ["cargo", "fmt", "-p", PACKAGE_WORKFLOW, "--", "--check"], tmp_path),
            (
                "cargo_clippy",
                ["cargo", "clippy", "-p", PACKAGE_WORKFLOW, "--all-targets", "--", "-D", "warnings"],
                tmp_path,
            ),
        ]

    def test_cross_crate_scope_uses_workspace_cargo_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cross-crate Rust scope maps to workspace Cargo commands."""
        _write_rust_workspace(tmp_path)
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE, STORAGE_SOURCE),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run()

        assert tool_calls == [
            ("cargo_fmt_check", ["cargo", "fmt", "--all", "--", "--check"], tmp_path),
            (
                "cargo_clippy",
                ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"],
                tmp_path,
            ),
        ]

    def test_run_all_uses_workspace_cargo_commands(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--all bypasses package-local scope for Rust lint."""
        _write_rust_workspace(tmp_path)
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run(run_all=True)

        assert tool_calls == [
            ("cargo_fmt_check", ["cargo", "fmt", "--all", "--", "--check"], tmp_path),
            (
                "cargo_clippy",
                ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"],
                tmp_path,
            ),
        ]

    def test_failing_rust_step_exits_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rust step failures propagate through the unified lint failure path."""
        _write_rust_workspace(tmp_path)

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE,),
            ),
        )

        def _fail_clippy(cmd: list[str], cwd: Path, step_name: str) -> None:
            _ = cmd, cwd
            if step_name == "cargo_clippy":
                raise SystemExit(17)

        monkeypatch.setattr("teleclaude.quality.lint._run_tool", _fail_clippy)

        with pytest.raises(SystemExit) as exc_info:
            LintRunner(project_root=tmp_path).run()

        assert exc_info.value.code == 17

    def test_typescript_only_project_runs_typescript_without_cargo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TypeScript lint behavior remains independent from Rust support."""
        tool_calls: list[tuple[str, list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["typescript"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(TYPESCRIPT_SOURCE,),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )
        (tmp_path / "teleclaude.yml").write_text(
            "languages:\n  - typescript\nfrontend_root: frontend\n",
            encoding="utf-8",
        )
        (tmp_path / "frontend" / "app").mkdir(parents=True)

        LintRunner(project_root=tmp_path).run()

        assert [name for name, _cmd, _cwd in tool_calls] == ["eslint", "tsc"]
        assert [call for call in tool_calls if call[1] and call[1][0] == "cargo"] == []

    def test_rust_steps_are_available_for_step_dispatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """telec code lint --step can dispatch a named Rust step when rust is declared."""
        _write_rust_workspace(tmp_path)
        tool_calls: list[tuple[str, list[str], Path]] = []

        (tmp_path / "teleclaude.yml").write_text("languages:\n  - rust\n", encoding="utf-8")
        monkeypatch.setattr(
            "teleclaude.quality.lint._run_tool",
            lambda cmd, cwd, step_name: tool_calls.append((step_name, list(cmd), cwd)),
        )

        LintRunner(project_root=tmp_path).run_step("cargo_clippy", [WORKFLOW_SOURCE])

        assert tool_calls == [
            (
                "cargo_clippy",
                ["cargo", "clippy", "-p", PACKAGE_WORKFLOW, "--all-targets", "--", "-D", "warnings"],
                tmp_path,
            )
        ]


# ---------------------------------------------------------------------------
# R1.6 — Failing step exits non-zero with tool-identifying diagnostic
# ---------------------------------------------------------------------------


class TestFailingStepDiagnostic:
    """Each failing pipeline step causes overall lint to exit non-zero."""

    def test_failing_guardrails_step_exits_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failing guardrails step causes the overall lint to exit non-zero."""
        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("teleclaude/foo.py",),
            ),
        )

        def _step_fail(_self: object, _targets: object) -> None:
            raise SystemExit(1)

        monkeypatch.setattr("teleclaude.quality.lint.GuardrailsStep.run", _step_fail)

        runner = LintRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run()
        assert exc_info.value.code != 0

    def test_pipeline_exposes_step_failure_identity(self, tmp_path: Path) -> None:
        """The pipeline identifies which tool step failed in its failure report."""
        pipeline = PythonLintPipeline(project_root=tmp_path)
        # Each step must have a name attribute for diagnostic identification
        for step in pipeline.steps:
            assert hasattr(step, "name"), f"Step {step!r} lacks a 'name' attribute for diagnostics"
            assert step.name, f"Step {step!r} has an empty name"


# ---------------------------------------------------------------------------
# R1 DoD §5 — Path validation: no traversal or injection via session scope
# ---------------------------------------------------------------------------


class TestPathValidation:
    """File path inputs from session scope must be validated against traversal and injection."""

    def test_traversal_paths_rejected_from_session_scope(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Paths containing '../' traversal sequences from session scope are rejected or stripped."""
        malicious_files = ["../../etc/passwd", "teleclaude/../../../shadow", "../traversal.py"]

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=tuple(malicious_files),
            ),
        )

        pipeline_targets: list[object] = []
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            pipeline_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        # Either the runner raises on invalid paths or filters them out
        try:
            runner.run()
        except (SystemExit, ValueError, RuntimeError):
            return  # Raising on traversal paths is a valid response

        # If it didn't raise, it must have filtered out all traversal paths
        if pipeline_targets:
            targets = pipeline_targets[0]
            if hasattr(targets, "__iter__") and not isinstance(targets, str):
                for t in targets:  # pyright: ignore[reportUnknownVariableType]
                    assert ".." not in str(t), (
                        f"Traversal path '{t}' was passed to the lint pipeline — path validation failed"
                    )

    def test_absolute_paths_outside_project_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Absolute paths outside the project root from session scope are rejected or stripped."""
        malicious_files = ["/etc/passwd", "/tmp/evil.py"]

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=tuple(malicious_files),
            ),
        )

        pipeline_targets: list[object] = []
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            pipeline_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        try:
            runner.run()
        except (SystemExit, ValueError, RuntimeError):
            return  # Raising on invalid paths is a valid response

        # If it didn't raise, absolute paths outside project must be filtered
        if pipeline_targets:
            targets = pipeline_targets[0]
            if hasattr(targets, "__iter__") and not isinstance(targets, str):
                for t in targets:  # pyright: ignore[reportUnknownVariableType]
                    t_str = str(t)
                    assert not Path(t_str).is_absolute() or t_str.startswith(str(tmp_path)), (
                        f"Absolute path '{t_str}' outside project root passed to pipeline"
                    )


# ---------------------------------------------------------------------------
# R6 — Single-step execution via `telec code lint --step <name>`
# ---------------------------------------------------------------------------


class TestRunStep:
    """LintRunner.run_step runs a single pipeline step on specific files.

    Required by R6: pre-commit hooks route each check through
    `telec code lint --step <name>` with the staged filenames pre-commit passes.
    """

    def test_run_step_dispatches_to_named_step_with_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_step finds the named step in the pipeline and calls its run() with the files."""
        captured: dict[str, list[str]] = {}

        class _Recording:
            """Stub pipeline step that records targets."""

            name = "ruff_check"

            def run(self, targets: list[str]) -> None:
                """Record targets for assertion."""
                captured["targets"] = list(targets)

        def _pipeline(project_root: Path | None = None) -> PythonLintPipeline:
            pipe = PythonLintPipeline(project_root=tmp_path)
            pipe.steps = [_Recording()]  # pyright: ignore[reportAttributeAccessIssue]
            return pipe

        monkeypatch.setattr("teleclaude.quality.lint.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr("teleclaude.quality.lint.PythonLintPipeline", _pipeline)

        runner = LintRunner(project_root=tmp_path)
        runner.run_step("ruff_check", ["a.py", "b.py"])

        assert captured.get("targets") == ["a.py", "b.py"]

    def test_run_step_rejects_unknown_step_name(self, tmp_path: Path) -> None:
        """Unknown step name exits non-zero — no silent no-op."""
        runner = LintRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run_step("bogus_step", [])
        assert exc_info.value.code != 0

    def test_run_step_rejects_traversal_files(self, tmp_path: Path) -> None:
        """All files rejected by path validation → exit 1, not silent pass."""
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        runner = LintRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run_step("guardrails", ["../etc/passwd"])
        assert exc_info.value.code == 1

    def test_run_step_with_empty_files_auto_scopes_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive --step (no files) resolves workspace scope, mirroring run().

        Without this, an agent running ``telec code lint --step guardrails``
        to spot-check their own work gets the whole repo's noise back —
        the same failure mode workspace scoping was designed to prevent for
        the no-step path.
        """
        scoped_files = ("teleclaude/foo.py",)
        captured: dict[str, list[str]] = {}

        class _Recording:
            name = "guardrails"

            def run(self, targets: list[str]) -> None:
                captured["targets"] = list(targets)

        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=scoped_files,
            ),
        )
        runner = LintRunner(project_root=tmp_path)
        monkeypatch.setattr(
            runner,
            "_collect_all_steps",
            lambda: {"guardrails": _Recording()},
        )

        runner.run_step("guardrails", [])

        assert captured.get("targets") == list(scoped_files)
