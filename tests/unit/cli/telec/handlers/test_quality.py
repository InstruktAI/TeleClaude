"""Tests for teleclaude.cli.telec.handlers.quality — CLI handler wiring."""

from __future__ import annotations

import pytest

from teleclaude.cli.telec.handlers.quality import _parse_step_args, handle_format, handle_lint, handle_test


class TestHandlerImports:
    """Handler functions are importable and callable."""

    def test_handle_lint_is_importable(self) -> None:
        """handle_lint can be imported from the quality handler module."""
        assert callable(handle_lint)

    def test_handle_test_is_importable(self) -> None:
        """handle_test can be imported from the quality handler module."""
        assert callable(handle_test)

    def test_handle_format_is_importable(self) -> None:
        """handle_format can be imported from the quality handler module."""
        assert callable(handle_format)


class TestParseStepArgs:
    """_parse_step_args extracts --step and positional filenames.

    Used by pre-commit hooks that pass staged filenames as positional args
    along with a --step flag to target a single pipeline step.
    """

    def test_no_step_flag_returns_none_and_all_args_as_files(self) -> None:
        """When --step is absent, every arg is a filename."""
        step, files = _parse_step_args(["a.py", "b.py"])
        assert step is None
        assert files == ["a.py", "b.py"]

    def test_step_flag_space_form_separates_step_from_files(self) -> None:
        """`--step ruff_check file1.py file2.py` parses correctly."""
        step, files = _parse_step_args(["--step", "ruff_check", "a.py", "b.py"])
        assert step == "ruff_check"
        assert files == ["a.py", "b.py"]

    def test_step_flag_equals_form_separates_step_from_files(self) -> None:
        """`--step=ruff_check file1.py` parses correctly."""
        step, files = _parse_step_args(["--step=guardrails", "a.py"])
        assert step == "guardrails"
        assert files == ["a.py"]

    def test_step_flag_without_value_raises(self) -> None:
        """A bare `--step` at end of args fails loudly, not silently."""
        with pytest.raises(SystemExit):
            _parse_step_args(["--step"])
