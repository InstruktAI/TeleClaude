"""Functional tests for delivery-time doc snippet reconciliation.

Spec: docs/project/spec/feature/context/lifecycle-marker-reconciliation.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.docs_reconcile import reconcile_delivered_snippets

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/lifecycle-marker-reconciliation"

# Sentinel tokens for the inline-marker fold test — the test asserts fold
# behavior (markers gone, replacement kept, current dropped), not any prose.
_INLINE_SLUG = "inline-slug"
_ADD_CONTENT = "INLINE-ADD-LIVE"
_CHANGE_CURRENT = "INLINE-CHANGE-CURRENT"
_CHANGE_REPLACEMENT = "INLINE-CHANGE-REPLACEMENT"


def _write_snippet(path: Path, body: str, *, delivered_by: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    delivered_by_line = f"delivered_by: {delivered_by}\n" if delivered_by is not None else ""
    path.write_text(
        f"""---
description: Reconcile fixture.
{delivered_by_line}---
{body}
""",
        encoding="utf-8",
    )


@pytest.mark.spec(_SPEC, "UC-LMR1")
def test_reconcile_delivered_snippets_resolves_owned_planned_change_only(tmp_path: Path, snapshot: object) -> None:
    parent = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "reconcile-target.md"
    _write_snippet(
        parent,
        """# Reconcile Target — Spec

## Canonical fields

Before.

<!-- planned-change:planned-change-markers -->
Current paragraph.
<!-- change:planned-change-markers -->
Replacement paragraph.
<!-- /planned-change:planned-change-markers -->

<!-- planned-change:other-slug -->
Other current paragraph.
<!-- change:other-slug -->
Other replacement paragraph.
<!-- /planned-change:other-slug -->

After.
""",
        delivered_by=["planned-change-markers"],
    )

    first_changed = [
        str(path.relative_to(tmp_path)) for path in reconcile_delivered_snippets(tmp_path, "planned-change-markers")
    ]
    content_after_first_run = parent.read_text(encoding="utf-8")
    second_changed = reconcile_delivered_snippets(tmp_path, "planned-change-markers")

    assert {
        "first_changed": first_changed,
        "content": content_after_first_run,
        "second_changed": second_changed,
    } == snapshot


def test_reconcile_folds_inline_markers(tmp_path: Path) -> None:
    """Inline markers (mid-prose) fold on delivery, not just own-line blocks."""
    parent = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "inline-target.md"
    _write_snippet(
        parent,
        f"# Inline Target — Spec\n\n"
        f"Lead-in <!-- planned:{_INLINE_SLUG} -->{_ADD_CONTENT}<!-- /planned:{_INLINE_SLUG} --> trailer.\n\n"
        f"Lead-in <!-- planned-change:{_INLINE_SLUG} -->{_CHANGE_CURRENT}"
        f"<!-- change:{_INLINE_SLUG} -->{_CHANGE_REPLACEMENT}"
        f"<!-- /planned-change:{_INLINE_SLUG} --> trailer.\n",
        delivered_by=[_INLINE_SLUG],
    )

    changed = reconcile_delivered_snippets(tmp_path, _INLINE_SLUG)
    result = parent.read_text(encoding="utf-8")

    assert parent in changed
    # Every trace of the delivered slug is gone — markers and delivered_by.
    assert _INLINE_SLUG not in result
    # ADD content becomes live; planned-change keeps the replacement, drops current.
    assert _ADD_CONTENT in result
    assert _CHANGE_REPLACEMENT in result
    assert _CHANGE_CURRENT not in result
    # Idempotent.
    assert reconcile_delivered_snippets(tmp_path, _INLINE_SLUG) == []
