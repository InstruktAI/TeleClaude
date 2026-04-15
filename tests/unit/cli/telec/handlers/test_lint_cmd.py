# guard: no-companion
# pylint: disable=import-outside-toplevel,not-an-iterable
"""Tests for R1: telec lint command.

Behavioral contracts for the telec lint command: language-aware lint pipeline
with automatic worktree scoping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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

        from teleclaude.quality.lint import resolve_project_root  # pyright: ignore[reportMissingImports]

        resolved = resolve_project_root(sub)
        assert resolved == tmp_path

    def test_raises_when_no_teleclaude_yml_found(self, tmp_path: Path) -> None:
        """Resolution raises an error when no teleclaude.yml is found in the hierarchy."""
        from teleclaude.quality.lint import resolve_project_root  # pyright: ignore[reportMissingImports]

        with pytest.raises((FileNotFoundError, RuntimeError, SystemExit)):
            resolve_project_root(tmp_path)


# ---------------------------------------------------------------------------
# R1.2 — Language detection from teleclaude.yml
# ---------------------------------------------------------------------------


class TestLanguageDetection:
    """Language is read from the project's teleclaude.yml."""

    def test_reads_python_language_from_config(self, tmp_path: Path) -> None:
        """teleclaude.yml with language:python returns 'python' as the project language."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        from teleclaude.quality.lint import get_project_language  # pyright: ignore[reportMissingImports]

        lang = get_project_language(tmp_path)
        assert lang == "python"

    def test_no_language_field_returns_none(self, tmp_path: Path) -> None:
        """teleclaude.yml without a language field returns None."""
        (tmp_path / "teleclaude.yml").write_text("business:\n  domains: {}\n", encoding="utf-8")

        from teleclaude.quality.lint import get_project_language  # pyright: ignore[reportMissingImports]

        lang = get_project_language(tmp_path)
        assert lang is None


# ---------------------------------------------------------------------------
# R1.3 — Worktree scope failure exits non-zero (no silent fallback)
# ---------------------------------------------------------------------------


class TestWorktreeScopeFailure:
    """In a worktree context, scope failure must exit non-zero — never silently fallback."""

    def test_scope_failure_in_worktree_exits_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When scope resolution fails in a worktree context, the command exits non-zero."""
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        def _fail_scope(_path: Path) -> list[str]:
            raise RuntimeError("session identity not found")

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: True)
        monkeypatch.setattr("teleclaude.quality.lint.resolve_session_scope", _fail_scope)

        runner = LintRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run()
        assert exc_info.value.code != 0

    def test_scope_failure_does_not_silently_fall_back_to_repo_wide(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Scope failure in worktree must never silently run against all source dirs."""
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        pipeline_calls: list[object] = []

        def _fail_scope(_path: Path) -> list[str]:
            raise RuntimeError("session identity not found")

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: True)
        monkeypatch.setattr("teleclaude.quality.lint.resolve_session_scope", _fail_scope)
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            pipeline_calls.append,
        )

        runner = LintRunner(project_root=tmp_path)
        try:
            runner.run()
        except SystemExit:
            pass
        # The pipeline must NOT have been called (no fallback to repo-wide)
        assert not pipeline_calls, "Pipeline ran after scope failure — silent fallback is forbidden"


# ---------------------------------------------------------------------------
# R1.4 — Non-worktree context runs against configured source dirs
# ---------------------------------------------------------------------------


class TestNonWorktreeContext:  # pylint: disable=too-few-public-methods
    """In non-worktree context, the command runs against the project's source dirs."""

    def test_non_worktree_receives_source_dirs_not_file_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Outside a worktree, the pipeline receives directory targets, not a file list."""
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: False)
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1
        targets_arg = received_targets[0]
        # Pipeline must receive non-empty targets (empty list = no linting)
        assert targets_arg, "Pipeline received empty targets in non-worktree mode"
        # Targets must not be individual .py files (those are worktree-scoped targets)
        if hasattr(targets_arg, "__iter__") and not isinstance(targets_arg, str):
            items = list(targets_arg)  # pyright: ignore[reportUnknownArgumentType]
            assert len(items) > 0, "Pipeline received empty iterable in non-worktree mode"
            for t in items:
                assert not str(t).endswith(".py"), (
                    f"Non-worktree target {t!r} is a .py file — expected directory targets"
                )


# ---------------------------------------------------------------------------
# R1.6 — Worktree context with successful scope passes file list to pipeline
# ---------------------------------------------------------------------------


class TestWorktreeScopeSuccess:
    """In a worktree context with successful scope resolution, the pipeline receives the scoped file list."""

    def test_worktree_success_passes_scoped_files_not_source_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When scope resolves successfully in a worktree, pipeline receives file list, not source dirs."""
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        scoped_files = ["teleclaude/foo/bar.py", "teleclaude/baz/qux.py"]
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: True)
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_session_scope",
            lambda _path: scoped_files,
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        assert len(received_targets) == 1, "Pipeline was not called exactly once"
        targets_arg = received_targets[0]
        # Must have received the scoped file list (individual .py paths), not source dirs
        if hasattr(targets_arg, "__iter__") and not isinstance(targets_arg, str):
            items = list(targets_arg)  # pyright: ignore[reportUnknownArgumentType]
            assert all(str(t).endswith(".py") for t in items), (
                f"Worktree pipeline received non-file targets — expected scoped .py files: {items}"
            )
            assert set(str(t) for t in items) == set(scoped_files), (
                f"Pipeline received wrong file set: {items} vs {scoped_files}"
            )

    def test_worktree_success_does_not_use_source_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """In a worktree with successful scope, source directories are not passed to the pipeline."""
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        scoped_files = ["teleclaude/quality/lint.py"]
        received_targets: list[object] = []

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: True)
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_session_scope",
            lambda _path: scoped_files,
        )
        monkeypatch.setattr(
            "teleclaude.quality.lint.run_pipeline",
            received_targets.append,
        )
        # Source dirs that should NOT appear
        (tmp_path / "teleclaude").mkdir()
        (tmp_path / "scripts").mkdir()

        runner = LintRunner(project_root=tmp_path)
        runner.run()

        targets_arg = received_targets[0] if received_targets else None
        assert targets_arg is not None
        if hasattr(targets_arg, "__iter__") and not isinstance(targets_arg, str):
            for t in targets_arg:  # pyright: ignore[reportUnknownVariableType]
                t_str = str(t)
                assert t_str not in ("teleclaude", "scripts"), (
                    f"Source directory '{t_str}' passed to pipeline in worktree mode"
                )


# ---------------------------------------------------------------------------
# R1.7 — Python pipeline deterministic order
# ---------------------------------------------------------------------------


class TestPythonPipelineOrder:  # pylint: disable=too-few-public-methods
    """The Python lint pipeline runs in a deterministic, required order."""

    def test_pipeline_steps_run_in_required_order(self, tmp_path: Path) -> None:
        """Pipeline order: guardrails, markdown, resource_validation, ruff, pyright, mypy, pylint."""
        from teleclaude.quality.lint import PythonLintPipeline  # pyright: ignore[reportMissingImports]

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
            "pylint",
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
        assert positions["pyright"] < positions["pylint"], "pyright must run before pylint"
        assert positions["mypy"] < positions["pylint"], "mypy must run before pylint"


# ---------------------------------------------------------------------------
# R1.6 — Failing step exits non-zero with tool-identifying diagnostic
# ---------------------------------------------------------------------------


class TestFailingStepDiagnostic:
    """Each failing pipeline step causes overall lint to exit non-zero."""

    def test_failing_guardrails_step_exits_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failing guardrails step causes the overall lint to exit non-zero."""
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: False)

        def _step_fail(_self: object, _targets: object) -> None:
            raise SystemExit(1)

        monkeypatch.setattr("teleclaude.quality.lint.GuardrailsStep.run", _step_fail)

        runner = LintRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run()
        assert exc_info.value.code != 0

    def test_pipeline_exposes_step_failure_identity(self, tmp_path: Path) -> None:
        """The pipeline identifies which tool step failed in its failure report."""
        from teleclaude.quality.lint import PythonLintPipeline  # pyright: ignore[reportMissingImports]

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
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        malicious_files = ["../../etc/passwd", "teleclaude/../../../shadow", "../traversal.py"]

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: True)
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_session_scope",
            lambda _path: malicious_files,
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
        from teleclaude.quality.lint import LintRunner  # pyright: ignore[reportMissingImports]

        malicious_files = ["/etc/passwd", "/tmp/evil.py"]

        monkeypatch.setattr("teleclaude.quality.lint.is_worktree", lambda _path: True)
        monkeypatch.setattr(
            "teleclaude.quality.lint.resolve_session_scope",
            lambda _path: malicious_files,
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
                    assert not t_str.startswith("/") or t_str.startswith(str(tmp_path)), (
                        f"Absolute path '{t_str}' outside project root passed to pipeline"
                    )
