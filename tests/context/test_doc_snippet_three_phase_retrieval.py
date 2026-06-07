"""Functional tests for doc-snippet three-phase retrieval.

Spec: docs/project/spec/feature/context/doc-snippet-three-phase-retrieval.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.context_selector import SnippetMeta, _build_phase1_output

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/doc-snippet-three-phase-retrieval"


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase1_appends_delivered_by_suffix_for_pending_snippets(tmp_path: Path, snapshot: object) -> None:
    """Phase-1 output appends ' (delivered by: a,b)' to pending snippets only."""
    current = SnippetMeta(
        snippet_id="project/spec/feature/context/current-snippet",
        description="A current snippet with no pending state.",
        snippet_type="spec",
        scope="project",
        path=tmp_path / "current.md",
        delivered_by=(),
    )
    pending = SnippetMeta(
        snippet_id="project/spec/feature/context/pending-snippet",
        description="A pending snippet owned by two slugs.",
        snippet_type="spec",
        scope="project",
        path=tmp_path / "pending.md",
        delivered_by=("slug-a", "slug-b"),
    )

    output = _build_phase1_output(
        [current, pending],
        [],
        areas=[],
        global_snippets_root=tmp_path,
        test_agent=None,
        test_mode=None,
        test_request=None,
        test_csv_path=None,
    )

    assert output == snapshot
