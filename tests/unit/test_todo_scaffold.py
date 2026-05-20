"""Tests for teleclaude.todo_scaffold.create_draft_skeleton content guard."""

from __future__ import annotations

import pytest

from teleclaude.todo_scaffold import create_draft_skeleton

_VALUE_ERROR = ValueError


class TestCreateDraftSkeletonContentGuard:
    @pytest.mark.unit
    def test_empty_content_raises_value_error(self) -> None:
        with pytest.raises(_VALUE_ERROR):
            create_draft_skeleton("root", "my-slug", content="")

    @pytest.mark.unit
    def test_none_content_raises_value_error(self) -> None:
        with pytest.raises(_VALUE_ERROR):
            create_draft_skeleton("root", "my-slug")

    @pytest.mark.unit
    def test_whitespace_only_content_raises_value_error(self) -> None:
        with pytest.raises(_VALUE_ERROR):
            create_draft_skeleton("root", "my-slug", content="   ")
