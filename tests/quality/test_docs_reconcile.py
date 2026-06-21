"""Functional tests for delivery-time doc snippet reconciliation.

Spec: docs/project/spec/feature/context/lifecycle-marker-reconciliation.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.docs_reconcile import (
    ResidualMarkerError,
    reconcile_delivered_snippets,
    reconcile_snippets_for_purged_slugs,
)

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/lifecycle-marker-reconciliation"
_REMOVAL_SPEC = "project/spec/feature/workflow/todo-removal"


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


_EOF_SLUG = "eof-add"
_EOF_KEPT_CONTENT = "Kept content."
_RESIDUAL_SLUG = "residual-demo"
_RESIDUAL_FILENAME = "residual.md"
_HAPPY_SLUG = "clean-slug"
_HAPPY_FILENAME = "clean.md"
_HAPPY_REPLACEMENT = "Replacement."


@pytest.mark.spec(_SPEC, "UC-LMR1")
def test_reconcile_strips_planned_add_close_at_eof_without_trailing_newline(tmp_path: Path) -> None:
    parent = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "eof-add.md"
    parent.parent.mkdir(parents=True, exist_ok=True)
    # The closing marker is the file's final line with no trailing newline.
    parent.write_text(
        "---\n"
        "description: Reconcile fixture.\n"
        f"delivered_by: ['{_EOF_SLUG}']\n"
        "---\n"
        "# EOF Add — Spec\n\n"
        "## Canonical fields\n\n"
        f"<!-- planned:{_EOF_SLUG} -->\n"
        f"{_EOF_KEPT_CONTENT}\n"
        f"<!-- /planned:{_EOF_SLUG} -->",
        encoding="utf-8",
    )

    reconcile_delivered_snippets(tmp_path, _EOF_SLUG)

    content = parent.read_text(encoding="utf-8")
    assert f"<!-- planned:{_EOF_SLUG} -->" not in content
    assert f"<!-- /planned:{_EOF_SLUG} -->" not in content
    assert _EOF_KEPT_CONTENT in content


@pytest.mark.spec(_SPEC, "UC-LMR1")
def test_reconcile_raises_loudly_on_residual_marker(tmp_path: Path) -> None:
    parent = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / _RESIDUAL_FILENAME
    # An inline planned-change the newline-anchored fold cannot resolve — it survives,
    # standing in for any future fold gap. The guard must fail loudly, not silently.
    _write_snippet(
        parent,
        "# Residual — Spec\n\n## Canonical fields\n\n"
        f"Before <!-- planned-change:{_RESIDUAL_SLUG} -->current"
        f"<!-- change:{_RESIDUAL_SLUG} -->replacement"
        f"<!-- /planned-change:{_RESIDUAL_SLUG} --> after.",
        delivered_by=[_RESIDUAL_SLUG],
    )

    with pytest.raises(ResidualMarkerError) as exc_info:
        reconcile_delivered_snippets(tmp_path, _RESIDUAL_SLUG)

    message = str(exc_info.value)
    assert _RESIDUAL_SLUG in message
    assert _RESIDUAL_FILENAME in message


@pytest.mark.spec(_SPEC, "UC-LMR1")
def test_reconcile_happy_path_returns_changed_paths(tmp_path: Path) -> None:
    parent = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / _HAPPY_FILENAME
    _write_snippet(
        parent,
        "# Clean — Spec\n\n## Canonical fields\n\n"
        f"<!-- planned-change:{_HAPPY_SLUG} -->\nCurrent.\n"
        f"<!-- change:{_HAPPY_SLUG} -->\n{_HAPPY_REPLACEMENT}\n<!-- /planned-change:{_HAPPY_SLUG} -->",
        delivered_by=[_HAPPY_SLUG],
    )

    changed = reconcile_delivered_snippets(tmp_path, _HAPPY_SLUG)

    assert [path.name for path in changed] == [_HAPPY_FILENAME]
    assert _HAPPY_REPLACEMENT in parent.read_text(encoding="utf-8")


@pytest.mark.spec(_REMOVAL_SPEC, "UC-TR-PURGE-STRIPS-INBODY-MARKERS")
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
