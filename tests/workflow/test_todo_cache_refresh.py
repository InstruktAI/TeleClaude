"""Functional tests for the daemon cache's todos refresh-detection boundary."""

from __future__ import annotations

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.core.cache import DaemonCache

pytestmark = pytest.mark.functional

_COMPUTER = "local"
_PROJECT = "/repo"


def _todo(*, prepare_review_verdict: str | None) -> TodoDTO:
    return TodoDTO(
        slug="blocked-by-review",
        status="active",
        has_requirements=False,
        has_impl_plan=True,
        lifecycle_phase="blocked",
        prepare_review_verdict=prepare_review_verdict,
    )


def test_apply_todos_snapshot_detects_a_verdict_only_change() -> None:
    cache = DaemonCache()

    first = cache.apply_todos_snapshot(_COMPUTER, {_PROJECT: [_todo(prepare_review_verdict=None)]})
    assert first is True

    changed = cache.apply_todos_snapshot(_COMPUTER, {_PROJECT: [_todo(prepare_review_verdict="changes_requested")]})
    assert changed is True

    no_delta = cache.apply_todos_snapshot(_COMPUTER, {_PROJECT: [_todo(prepare_review_verdict="changes_requested")]})
    assert no_delta is False
