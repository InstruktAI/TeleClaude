# pylint: disable=import-outside-toplevel
"""Tests for teleclaude.quality.scope — shared scope utilities."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestResolveProjectRoot:  # pylint: disable=too-few-public-methods
    """resolve_project_root walks up to find teleclaude.yml."""

    def test_finds_root_with_teleclaude_yml(self, tmp_path: Path) -> None:
        """Returns the directory containing teleclaude.yml."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)

        from teleclaude.quality.scope import resolve_project_root

        assert resolve_project_root(sub) == tmp_path


class TestValidateScopedPaths:
    """validate_scoped_paths filters out dangerous paths."""

    def test_filters_traversal_paths(self, tmp_path: Path) -> None:
        """Paths containing '..' are rejected."""
        from teleclaude.quality.scope import validate_scoped_paths

        result = validate_scoped_paths(["../etc/passwd", "ok.py"], tmp_path)
        assert result == ["ok.py"]

    def test_filters_absolute_paths_outside_root(self, tmp_path: Path) -> None:
        """Absolute paths outside project root are rejected."""
        from teleclaude.quality.scope import validate_scoped_paths

        result = validate_scoped_paths(["/etc/passwd", "ok.py"], tmp_path)
        assert result == ["ok.py"]


class TestGetProjectLanguages:
    """get_project_languages reads the languages list from teleclaude.yml."""

    def test_returns_languages_list_from_config(self, tmp_path: Path) -> None:
        """Reads the languages list when present."""
        (tmp_path / "teleclaude.yml").write_text("languages:\n  - python\n  - typescript\n", encoding="utf-8")

        from teleclaude.quality.scope import get_project_languages

        assert get_project_languages(tmp_path) == ["python", "typescript"]

    def test_falls_back_to_singular_language_field(self, tmp_path: Path) -> None:
        """Backward compat: wraps singular language in a list."""
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        from teleclaude.quality.scope import get_project_languages

        assert get_project_languages(tmp_path) == ["python"]

    def test_prefers_languages_over_language(self, tmp_path: Path) -> None:
        """When both fields exist, languages takes precedence."""
        (tmp_path / "teleclaude.yml").write_text("language: python\nlanguages:\n  - typescript\n", encoding="utf-8")

        from teleclaude.quality.scope import get_project_languages

        assert get_project_languages(tmp_path) == ["typescript"]

    def test_returns_empty_list_when_no_language_fields(self, tmp_path: Path) -> None:
        """Returns empty list when neither field exists."""
        (tmp_path / "teleclaude.yml").write_text("business:\n  domains: {}\n", encoding="utf-8")

        from teleclaude.quality.scope import get_project_languages

        assert get_project_languages(tmp_path) == []

    def test_returns_empty_list_when_no_config_file(self, tmp_path: Path) -> None:
        """Returns empty list when teleclaude.yml doesn't exist."""
        from teleclaude.quality.scope import get_project_languages

        assert get_project_languages(tmp_path) == []


class TestResolveInvocationCwd:
    """resolve_invocation_cwd returns the user's actual invocation directory.

    R1 regression guard: the bin/telec wrapper uses `uv run --directory` which
    sets the Python process cwd to TeleClaude's install root. `Path.cwd()`
    then no longer reflects the directory the user was in. Handlers must use
    this helper (not `Path.cwd()`) so worktree scoping survives the wrapper.
    """

    def test_prefers_telec_env_var_over_pwd_and_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TELEC_INVOCATION_CWD wins over PWD and Path.cwd()."""
        from teleclaude.project_root import resolve_invocation_cwd

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
        from teleclaude.project_root import resolve_invocation_cwd

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
        from teleclaude.project_root import resolve_invocation_cwd

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
        from teleclaude.project_root import resolve_invocation_cwd
        from teleclaude.quality.scope import resolve_project_root

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

        resolved = resolve_project_root(resolve_invocation_cwd())
        assert resolved == worktree, (
            f"Expected worktree {worktree}, got {resolved}. The wrapper-cwd hijack bypassed invocation-cwd resolution."
        )
