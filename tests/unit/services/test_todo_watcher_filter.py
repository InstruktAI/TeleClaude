# guard: no-companion
# pyright: reportMissingImports=false
"""Test spec (xfail) for todo watcher path filtering - R1.2, R1.3, R1.4, R1.5.

Covers path normalization, noise filtering, move-event handling, and the
path allowlist. All tests are marked xfail — remove the marker once
implementation satisfies each test.

Target module: wherever the builder places the filtering logic for the
OS-managed todo watcher process.
"""
# pylint: disable=import-outside-toplevel,missing-function-docstring

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# R1.2 — Path Normalization
# ---------------------------------------------------------------------------


class TestPathNormalization:
    """Reported paths must be project-relative with POSIX separators."""

    def test_absolute_path_becomes_project_relative(self) -> None:
        from teleclaude.services.todo_watcher import normalize_path

        result = normalize_path("/home/user/project", "/home/user/project/todos/my-slug/state.yaml")
        assert result == "todos/my-slug/state.yaml"

    def test_trailing_slash_on_project_root_handled(self) -> None:
        from teleclaude.services.todo_watcher import normalize_path

        result = normalize_path("/home/user/project/", "/home/user/project/todos/roadmap.yaml")
        assert result == "todos/roadmap.yaml"

    def test_backslash_separators_normalized_to_posix(self) -> None:
        from teleclaude.services.todo_watcher import normalize_path

        result = normalize_path("/home/user/project", "/home/user/project/todos\\my-slug\\state.yaml")
        assert result == "todos/my-slug/state.yaml"

    def test_result_has_no_leading_slash(self) -> None:
        from teleclaude.services.todo_watcher import normalize_path

        result = normalize_path("/project", "/project/todos/slug/state.yaml")
        assert not result.startswith("/")


# ---------------------------------------------------------------------------
# R1.3 — Move Event Handling
# ---------------------------------------------------------------------------


class TestMoveEventHandling:
    """For move/rename events, both source and destination are evaluated."""

    def test_move_source_matching_is_reported(self) -> None:
        """A move FROM a matching path should be included."""
        from teleclaude.services.todo_watcher import evaluate_move_event

        src = "todos/my-slug/state.yaml"
        dst = "archive/old-state.yaml"
        result = evaluate_move_event(src, dst)
        assert src in result

    def test_move_destination_matching_is_reported(self) -> None:
        """A move TO a matching path should be included."""
        from teleclaude.services.todo_watcher import evaluate_move_event

        src = "staging/state.yaml"
        dst = "todos/my-slug/state.yaml"
        result = evaluate_move_event(src, dst)
        assert dst in result

    def test_move_both_matching_reports_both(self) -> None:
        """Both paths reported when both match the allowlist."""
        from teleclaude.services.todo_watcher import evaluate_move_event

        src = "todos/old-slug/state.yaml"
        dst = "todos/new-slug/state.yaml"
        result = evaluate_move_event(src, dst)
        assert src in result
        assert dst in result

    def test_move_neither_matching_reports_empty(self) -> None:
        """Neither path reported when both are outside the allowlist."""
        from teleclaude.services.todo_watcher import evaluate_move_event

        src = "src/main.py"
        dst = "src/app.py"
        result = evaluate_move_event(src, dst)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# R1.4 — Noise Filtering
# ---------------------------------------------------------------------------


class TestNoiseFiltering:
    """Hidden files/dirs and temp/editor artifacts are rejected before matching."""

    @pytest.mark.parametrize(
        "path",
        [
            "todos/.hidden/state.yaml",
            ".git/todos/state.yaml",
            "todos/my-slug/.state.yaml",
            "todos/.DS_Store",
        ],
        ids=["hidden-dir-inside-todos", "dotgit-prefix", "hidden-file", "ds-store"],
    )
    def test_hidden_paths_rejected(self, path: str) -> None:
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "todos/my-slug/state.yaml.swp",
            "todos/my-slug/requirements.md.bak",
            "todos/my-slug/state.yaml~",
            "todos/my-slug/.state.yaml.swx",
            "todos/my-slug/requirements.md.tmp",
        ],
        ids=["vim-swap", "backup-file", "tilde-suffix", "vim-swx", "tmp-file"],
    )
    def test_editor_temp_artifacts_rejected(self, path: str) -> None:
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed(path) is False

    def test_noise_filtering_precedes_allowlist(self) -> None:
        """A path that matches the allowlist pattern but is a temp file must be rejected."""
        from teleclaude.services.todo_watcher import is_path_allowed

        # This matches todos/*/*.yaml but is a swap file
        assert is_path_allowed("todos/my-slug/state.yaml.swp") is False


# ---------------------------------------------------------------------------
# R1.5 — Path Allowlist: File Patterns
# ---------------------------------------------------------------------------


class TestFilePatternAllowlist:
    """Only changes matching the specified file patterns are reported."""

    @pytest.mark.parametrize(
        "path",
        [
            # todos/*.yaml
            "todos/roadmap.yaml",
            "todos/delivered.yaml",
            # todos/*/*.md
            "todos/my-slug/requirements.md",
            "todos/my-slug/input.md",
            # todos/*/*.yaml
            "todos/my-slug/state.yaml",
            # todos/_icebox/icebox.yaml
            "todos/_icebox/icebox.yaml",
            # todos/_icebox/*/*.md
            "todos/_icebox/old-feature/requirements.md",
            # todos/_icebox/*/*.yaml
            "todos/_icebox/old-feature/state.yaml",
            # trees/*/todos/*/*.md
            "trees/feature-branch/todos/my-slug/requirements.md",
            # trees/*/todos/*/*.yaml
            "trees/feature-branch/todos/my-slug/state.yaml",
        ],
        ids=[
            "todos-roadmap-yaml",
            "todos-delivered-yaml",
            "todos-slug-md",
            "todos-slug-input-md",
            "todos-slug-yaml",
            "icebox-yaml",
            "icebox-slug-md",
            "icebox-slug-yaml",
            "trees-slug-todos-md",
            "trees-slug-todos-yaml",
        ],
    )
    def test_matching_file_patterns_accepted(self, path: str) -> None:
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            # Not under todos/ or trees/
            "src/main.py",
            "README.md",
            # Too deep under todos/
            "todos/slug/nested/deep/file.yaml",
            # Wrong extension under todos/*
            "todos/roadmap.md",
            # Wrong extension at slug level
            "todos/my-slug/notes.txt",
            "todos/my-slug/data.json",
            # Direct file in todos/_icebox (not icebox.yaml)
            "todos/_icebox/random.md",
            # File directly in trees/ (no slug)
            "trees/state.yaml",
            # File in trees/*/todos/ (no slug level)
            "trees/branch/todos/roadmap.yaml",
            # Completely unrelated
            "teleclaude/core/something.py",
            ".github/workflows/ci.yml",
        ],
        ids=[
            "src-file",
            "root-readme",
            "too-deep-nested",
            "wrong-ext-at-top",
            "txt-in-slug",
            "json-in-slug",
            "icebox-random-md",
            "trees-root-file",
            "trees-todos-no-slug",
            "unrelated-source",
            "github-workflow",
        ],
    )
    def test_non_matching_file_patterns_rejected(self, path: str) -> None:
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed(path) is False


# ---------------------------------------------------------------------------
# R1.5 — Path Allowlist: Directory Events
# ---------------------------------------------------------------------------


class TestDirectoryEventAllowlist:
    """Directory create/delete/move events for specific paths are reported."""

    @pytest.mark.parametrize(
        "path",
        [
            "todos/my-slug",
            "todos/new-feature",
            "todos/_icebox/archived-slug",
            "trees/feature-branch",
            "trees/feature-branch/todos/my-slug",
        ],
        ids=[
            "todos-slug-dir",
            "todos-new-feature-dir",
            "icebox-slug-dir",
            "trees-slug-dir",
            "trees-slug-todos-slug-dir",
        ],
    )
    def test_matching_directory_events_accepted(self, path: str) -> None:
        from teleclaude.services.todo_watcher import is_dir_event_allowed

        assert is_dir_event_allowed(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            # Not a recognized directory pattern
            "src",
            "todos",
            "trees",
            "todos/_icebox",
            "todos/slug/nested",
            "trees/branch/src",
        ],
        ids=[
            "src-dir",
            "todos-root",
            "trees-root",
            "icebox-root",
            "nested-inside-slug",
            "trees-src-dir",
        ],
    )
    def test_non_matching_directory_events_rejected(self, path: str) -> None:
        from teleclaude.services.todo_watcher import is_dir_event_allowed

        assert is_dir_event_allowed(path) is False


# ---------------------------------------------------------------------------
# R1.5 — Boundary Cases
# ---------------------------------------------------------------------------


class TestAllowlistBoundaries:
    """Edge cases and boundaries for allowlist matching."""

    def test_icebox_yaml_only_at_exact_path(self) -> None:
        """Only todos/_icebox/icebox.yaml matches, not any yaml in _icebox root."""
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed("todos/_icebox/icebox.yaml") is True
        assert is_path_allowed("todos/_icebox/other.yaml") is False

    def test_trees_requires_two_levels_for_files(self) -> None:
        """trees/*/todos/*/*.yaml requires a slug under todos."""
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed("trees/branch/todos/slug/state.yaml") is True
        assert is_path_allowed("trees/branch/state.yaml") is False

    def test_slug_with_hyphens_and_numbers(self) -> None:
        """Slugs containing hyphens and numbers are valid."""
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed("todos/my-feature-123/state.yaml") is True

    def test_deeply_nested_worktree_todo_not_matched(self) -> None:
        """Only one level of nesting under trees/*/todos/*/."""
        from teleclaude.services.todo_watcher import is_path_allowed

        assert is_path_allowed("trees/branch/todos/slug/deep/state.yaml") is False
