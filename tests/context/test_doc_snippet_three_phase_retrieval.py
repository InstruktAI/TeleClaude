"""Functional tests for doc-snippet three-phase retrieval.

Spec: docs/project/spec/feature/context/doc-snippet-three-phase-retrieval.md
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teleclaude.context_selector import SnippetMeta, _build_phase1_output, build_context_output

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/doc-snippet-three-phase-retrieval"
_SNIPPET_ID = "project/spec/feature/context/target-lens"


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase1_appends_delivered_by_suffix_for_pending_snippets(tmp_path: Path, snapshot: object) -> None:
    """Phase-1 output appends ' (delivered by: a,b)' to pending snippets only."""
    current = SnippetMeta(
        snippet_id="project/spec/feature/context/current-snippet",
        description="A current snippet with no pending state.",
        snippet_type="spec",
        scope="project",
        domain="project",
        path=tmp_path / "current.md",
        delivered_by=(),
    )
    pending = SnippetMeta(
        snippet_id="project/spec/feature/context/pending-snippet",
        description="A pending snippet owned by two slugs.",
        snippet_type="spec",
        scope="project",
        domain="project",
        path=tmp_path / "pending.md",
        delivered_by=("slug-a", "slug-b"),
    )

    output = _build_phase1_output(
        [current, pending],
        [],
        areas=[],
        test_agent=None,
        test_mode=None,
        test_request=None,
        test_csv_path=None,
    )

    assert output == snapshot


def _write_snippet(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: {_SNIPPET_ID}
type: spec
domain: software-development
scope: project
description: Target lens snippet.
---
{body}
""",
        encoding="utf-8",
    )


def _write_index(project_root: Path, snippet_path: Path) -> None:
    index_path = project_root / "docs" / "project" / "index.yaml"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "snippets": [
                    {
                        "id": _SNIPPET_ID,
                        "description": "Target lens snippet.",
                        "type": "spec",
                        "scope": "project",
                        "domain": "project",
                        "visibility": "public",
                        "path": str(snippet_path.relative_to(project_root)),
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _phase2_output(project_root: Path, *, target_slug: str | None) -> str:
    return build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=[_SNIPPET_ID],
        target_slug=target_slug,
    )


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase2_target_uses_matching_companion_replacement_body(tmp_path: Path, snapshot: object) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "target-lens.md"
    _write_snippet(snippet_path, "# Live Parent\n\nLive parent body.\n")
    _write_snippet(
        snippet_path.with_name("target-lens.fix-docs-get-target-companion-bodies.md"),
        "# Companion\n\nCompanion replacement body.\n",
    )
    _write_index(tmp_path, snippet_path)

    assert _phase2_output(tmp_path, target_slug="fix-docs-get-target-companion-bodies") == snapshot


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase2_plain_read_keeps_matching_companion_invisible(tmp_path: Path, snapshot: object) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "target-lens.md"
    _write_snippet(snippet_path, "# Live Parent\n\nLive parent body.\n")
    _write_snippet(
        snippet_path.with_name("target-lens.fix-docs-get-target-companion-bodies.md"),
        "# Companion\n\nCompanion replacement body.\n",
    )
    _write_index(tmp_path, snippet_path)

    assert _phase2_output(tmp_path, target_slug=None) == snapshot


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase2_non_owning_target_keeps_matching_companion_invisible(tmp_path: Path, snapshot: object) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "target-lens.md"
    _write_snippet(snippet_path, "# Live Parent\n\nLive parent body.\n")
    _write_snippet(
        snippet_path.with_name("target-lens.fix-docs-get-target-companion-bodies.md"),
        "# Companion\n\nCompanion replacement body.\n",
    )
    _write_index(tmp_path, snippet_path)

    assert _phase2_output(tmp_path, target_slug="other-slug") == snapshot


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase2_target_still_resolves_inline_planned_sections(tmp_path: Path, snapshot: object) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "target-lens.md"
    _write_snippet(
        snippet_path,
        """# Live Parent

Live parent body.

<!-- planned:fix-docs-get-target-companion-bodies -->
# Planned Body

Planned replacement body.
<!-- /planned:fix-docs-get-target-companion-bodies -->
""",
    )
    _write_index(tmp_path, snippet_path)

    assert {
        "target": _phase2_output(tmp_path, target_slug="fix-docs-get-target-companion-bodies"),
        "plain": _phase2_output(tmp_path, target_slug=None),
    } == snapshot
