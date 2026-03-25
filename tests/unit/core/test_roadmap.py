"""Characterization tests for teleclaude.core.roadmap."""

from __future__ import annotations

import textwrap

import pytest

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.models import TodoInfo

# _slugify_heading: pure slug normalization logic; tested directly since it has
# no public wrapper and is the canonical slug contract used throughout the module.
from teleclaude.core.roadmap import _derive_phase_status, _slugify_heading, assemble_roadmap


def _scaffold_todo(tmp_path, slug, *, roadmap=True, state_yaml="", files=None):
    """Create a minimal todo structure on the main branch."""
    todos = tmp_path / "todos"
    todos.mkdir(exist_ok=True)
    if roadmap:
        existing = (todos / "roadmap.yaml").read_text() if (todos / "roadmap.yaml").exists() else ""
        (todos / "roadmap.yaml").write_text(existing + f"- slug: {slug}\n")
    slug_dir = todos / slug
    slug_dir.mkdir(exist_ok=True)
    if state_yaml:
        (slug_dir / "state.yaml").write_text(state_yaml)
    for filename in files or []:
        (slug_dir / filename).write_text(f"scaffold: {filename}")
    return slug_dir


def _scaffold_worktree_todo(tmp_path, slug, *, state_yaml="", files=None):
    """Create a todo structure in the worktree for the given slug."""
    wt_todo = tmp_path / WORKTREE_DIR / slug / "todos" / slug
    wt_todo.mkdir(parents=True, exist_ok=True)
    if state_yaml:
        (wt_todo / "state.yaml").write_text(state_yaml)
    for filename in files or []:
        (wt_todo / filename).write_text(f"worktree: {filename}")
    return wt_todo


class TestAssembleRoadmap:
    @pytest.mark.unit
    def test_missing_todos_dir_returns_empty(self, tmp_path):
        result = assemble_roadmap(str(tmp_path))
        assert result == []

    @pytest.mark.unit
    def test_empty_todos_dir_returns_empty(self, tmp_path):
        (tmp_path / "todos").mkdir()
        result = assemble_roadmap(str(tmp_path))
        assert result == []

    @pytest.mark.unit
    def test_roadmap_with_one_entry_returns_one_item(self, tmp_path):
        todos = tmp_path / "todos"
        todos.mkdir()
        (todos / "roadmap.yaml").write_text("- slug: my-feature\n  description: My feature\n")
        (todos / "my-feature").mkdir()
        result = assemble_roadmap(str(tmp_path))
        assert len(result) == 1
        assert isinstance(result[0], TodoInfo)
        assert result[0].slug == "my-feature"
        assert result[0].description == "My feature"


class TestWorktreeResolution:
    """Worktree todo directories take precedence over main branch."""

    @pytest.mark.unit
    def test_worktree_files_win_over_main(self, tmp_path):
        _scaffold_todo(tmp_path, "feat", files=["input.md", "state.yaml"])
        _scaffold_worktree_todo(tmp_path, "feat", files=["input.md", "requirements.md", "implementation-plan.md"])

        result = assemble_roadmap(str(tmp_path))
        assert len(result) == 1
        todo = result[0]
        assert "requirements.md" in todo.files
        assert "implementation-plan.md" in todo.files
        assert todo.has_requirements is True
        assert todo.has_impl_plan is True

    @pytest.mark.unit
    def test_worktree_state_wins_over_main(self, tmp_path):
        main_state = textwrap.dedent("""\
            schema_version: 2
            phase: pending
            current: input_assessment
        """)
        wt_state = textwrap.dedent("""\
            schema_version: 2
            phase: pending
            current: plan_drafting
        """)
        _scaffold_todo(tmp_path, "feat", state_yaml=main_state)
        _scaffold_worktree_todo(tmp_path, "feat", state_yaml=wt_state)

        result = assemble_roadmap(str(tmp_path))
        assert result[0].prepare_phase == "plan_drafting"

    @pytest.mark.unit
    def test_todo_path_points_to_worktree_when_exists(self, tmp_path):
        _scaffold_todo(tmp_path, "feat")
        wt_dir = _scaffold_worktree_todo(tmp_path, "feat")

        result = assemble_roadmap(str(tmp_path))
        assert result[0].todo_path == str(wt_dir)

    @pytest.mark.unit
    def test_todo_path_points_to_main_when_no_worktree(self, tmp_path):
        main_dir = _scaffold_todo(tmp_path, "feat")

        result = assemble_roadmap(str(tmp_path))
        assert result[0].todo_path == str(main_dir)

    @pytest.mark.unit
    def test_main_used_when_no_worktree_exists(self, tmp_path):
        _scaffold_todo(tmp_path, "feat", files=["input.md", "requirements.md"])

        result = assemble_roadmap(str(tmp_path))
        todo = result[0]
        assert "requirements.md" in todo.files
        assert todo.has_requirements is True

    @pytest.mark.unit
    def test_worktree_has_requirements_false_when_main_has_it(self, tmp_path):
        """Worktree wins even when it lacks files that main has."""
        _scaffold_todo(tmp_path, "feat", files=["requirements.md"])
        _scaffold_worktree_todo(tmp_path, "feat", files=["input.md"])

        result = assemble_roadmap(str(tmp_path))
        todo = result[0]
        assert todo.has_requirements is False
        assert "requirements.md" not in todo.files


class TestDerivePhaseStatus:
    """Phase status derivation from state fields."""

    @pytest.mark.unit
    def test_active_prepare_phase_is_in_progress(self):
        assert _derive_phase_status("pending", "pending", 0, "plan_drafting") == "in_progress"

    @pytest.mark.unit
    def test_input_assessment_is_in_progress(self):
        assert _derive_phase_status("pending", "pending", 0, "input_assessment") == "in_progress"

    @pytest.mark.unit
    def test_triangulation_is_in_progress(self):
        assert _derive_phase_status("pending", "pending", 0, "triangulation") == "in_progress"

    @pytest.mark.unit
    def test_prepared_is_ready(self):
        assert _derive_phase_status("pending", "pending", 0, "prepared") == "ready"

    @pytest.mark.unit
    def test_no_prepare_phase_is_pending(self):
        assert _derive_phase_status("pending", "pending", 0, None) == "pending"

    @pytest.mark.unit
    def test_high_dor_score_is_ready(self):
        assert _derive_phase_status("pending", "pending", 8, None) == "ready"

    @pytest.mark.unit
    def test_build_not_pending_is_in_progress(self):
        assert _derive_phase_status("pending", "complete", 0, None) == "in_progress"

    @pytest.mark.unit
    def test_raw_phase_in_progress_wins(self):
        assert _derive_phase_status("in_progress", "pending", 0, None) == "in_progress"


class TestSlugifyHeading:
    @pytest.mark.unit
    def test_simple_heading_lowercased_and_hyphenated(self):
        result = _slugify_heading("My Feature Title")
        assert result == "my-feature-title"

    @pytest.mark.unit
    def test_special_chars_replaced_with_hyphen(self):
        result = _slugify_heading("Feature: Add (OAuth)")
        assert result == "feature-add-oauth"

    @pytest.mark.unit
    def test_leading_trailing_hyphens_stripped(self):
        result = _slugify_heading("-Leading Trailing-")
        assert not result.startswith("-")
        assert not result.endswith("-")

    @pytest.mark.unit
    def test_numbers_preserved(self):
        result = _slugify_heading("Phase 2 Implementation")
        assert result == "phase-2-implementation"

    @pytest.mark.unit
    def test_already_slug_unchanged(self):
        result = _slugify_heading("my-feature")
        assert result == "my-feature"

    @pytest.mark.unit
    def test_multiple_spaces_collapsed(self):
        result = _slugify_heading("hello   world")
        assert result == "hello-world"
