"""Functional tests for todo removal purge-time snippet reconciliation.

Spec: docs/project/spec/feature/workflow/todo-removal.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.docs_reconcile import reconcile_snippets_for_purged_slugs

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-removal"


def _write_snippet(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
description: Purge fixture.
---
{body}
""",
        encoding="utf-8",
    )


@pytest.mark.spec(_SPEC, "UC-TR-PURGE-STRIPS-INBODY-MARKERS")
def test_purge_abandons_in_body_markers_for_purged_slug(tmp_path: Path, snapshot: object) -> None:
    snippet = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "purge-target.md"
    _write_snippet(
        snippet,
        """# Purge Target — Spec

## Canonical fields

Before.

<!-- planned:purged-slug -->
Abandoned addition.
<!-- /planned:purged-slug -->

<!-- planned-change:purged-slug -->
Original paragraph.
<!-- change:purged-slug -->
Replacement paragraph.
<!-- /planned-change:purged-slug -->

<!-- planned:other-slug -->
Other addition.
<!-- /planned:other-slug -->

After.
""",
    )

    plans = reconcile_snippets_for_purged_slugs(tmp_path, ["purged-slug"], {})

    # The snapshot pins the abandon fold: the purged slug's planned ADD block is
    # dropped with its content, its planned-change reverts to the original side, and
    # the other slug's marker survives untouched.
    assert [plan.path.name for plan in plans] == ["purge-target.md"]
    assert plans[0].rendered_content == snapshot


def test_purge_leaves_snippets_without_the_slug_untouched(tmp_path: Path) -> None:
    snippet = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "unrelated.md"
    _write_snippet(
        snippet,
        "# Unrelated — Spec\n\n## Canonical fields\n\n"
        "<!-- planned:other-slug -->\nOther addition.\n<!-- /planned:other-slug -->\n",
    )

    plans = reconcile_snippets_for_purged_slugs(tmp_path, ["purged-slug"], {})

    assert plans == []
