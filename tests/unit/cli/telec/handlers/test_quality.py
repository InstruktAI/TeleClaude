# pylint: disable=import-outside-toplevel
"""Tests for teleclaude.cli.telec.handlers.quality — CLI handler wiring."""

from __future__ import annotations


class TestHandlerImports:
    """Handler functions are importable and callable."""

    def test_handle_lint_is_importable(self) -> None:
        """handle_lint can be imported from the quality handler module."""
        from teleclaude.cli.telec.handlers.quality import handle_lint

        assert callable(handle_lint)

    def test_handle_test_is_importable(self) -> None:
        """handle_test can be imported from the quality handler module."""
        from teleclaude.cli.telec.handlers.quality import handle_test

        assert callable(handle_test)
