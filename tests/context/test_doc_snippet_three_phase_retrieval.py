"""Functional tests for doc-snippet three-phase retrieval.

Spec: docs/project/spec/feature/context/doc-snippet-three-phase-retrieval.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import pytest

from teleclaude.cli.telec.handlers import docs as docs_handler
from teleclaude.cli.telec.handlers.docs import _handle_docs_get, _handle_docs_index
from teleclaude.context_selector import SnippetMeta, _build_phase1_output, build_context_output

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/doc-snippet-three-phase-retrieval"
_SNIPPET_ID = "project/spec/feature/context/target-lens"


class _IndexEntry(TypedDict, total=False):
    id: str
    description: str
    type: str
    scope: str
    domain: str
    visibility: str
    path: str
    superseded_by: list[str]


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase1_appends_lifecycle_suffixes_for_pending_snippets(tmp_path: Path, snapshot: object) -> None:
    """Phase-1 output appends lifecycle suffixes to pending snippets only."""
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
    superseded = SnippetMeta(
        snippet_id="project/spec/feature/context/superseded-snippet",
        description="A current snippet with an in-flight change.",
        snippet_type="spec",
        scope="project",
        domain="project",
        path=tmp_path / "superseded.md",
        superseded_by=("slug-c",),
    )

    output = _build_phase1_output(
        [current, pending, superseded],
        [],
        areas=[],
        test_agent=None,
        test_mode=None,
        test_request=None,
        test_csv_path=None,
    )

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-3PR3")
def test_phase1_target_lists_delivered_and_superseded_snippets(tmp_path: Path) -> None:
    """index --target lists both the slug's new (delivered_by) and reworked (superseded_by) snippets."""
    target = "retire-todo-split"
    base = "project/spec/feature/context"
    docs_dir = tmp_path / "docs" / "project" / "spec" / "feature" / "context"
    docs_dir.mkdir(parents=True, exist_ok=True)

    def _entry(name: str, **lifecycle: list[str]) -> _IndexEntry:
        snippet_path = docs_dir / f"{name}.md"
        _write_snippet_named(snippet_path, f"{base}/{name}", f"# {name}\n\nBody.\n")
        entry: _IndexEntry = {
            "id": f"{base}/{name}",
            "description": f"{name} snippet.",
            "type": "spec",
            "scope": "project",
            "domain": "project",
            "visibility": "public",
            "path": str(snippet_path.relative_to(tmp_path)),
        }
        entry.update(lifecycle)  # type: ignore[typeddict-item]
        return entry

    index_path = tmp_path / "docs" / "project" / "index.yaml"
    index_path.write_text(
        json.dumps(
            {
                "project_root": str(tmp_path),
                "snippets": [
                    _entry("new-snippet", delivered_by=[target]),
                    _entry("reworked-snippet", superseded_by=[target]),
                    _entry("unrelated-snippet"),
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    output = build_context_output(
        areas=[],
        project_root=tmp_path,
        snippet_ids=None,
        target_slug=target,
    )

    assert f"{base}/new-snippet" in output
    assert f"{base}/reworked-snippet" in output
    assert f"{base}/unrelated-snippet" not in output


def _write_snippet_named(path: Path, snippet_id: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: {snippet_id}
type: spec
domain: software-development
scope: project
description: {snippet_id} snippet.
---
{body}
""",
        encoding="utf-8",
    )


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


def _write_index(project_root: Path, snippet_path: Path, *, superseded_by: list[str] | None = None) -> None:
    entry: _IndexEntry = {
        "id": _SNIPPET_ID,
        "description": "Target lens snippet.",
        "type": "spec",
        "scope": "project",
        "domain": "project",
        "visibility": "public",
        "path": str(snippet_path.relative_to(project_root)),
    }
    if superseded_by:
        entry["superseded_by"] = superseded_by
    index_path = project_root / "docs" / "project" / "index.yaml"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "snippets": [entry],
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
def test_phase1_orders_by_taxonomy_type_then_scope_then_id(tmp_path: Path) -> None:
    """Phase-1 lists every snippet in taxonomy general-to-specific order, scope then ID within a type."""

    def _meta(snippet_id: str, snippet_type: str, scope: str) -> SnippetMeta:
        return SnippetMeta(
            snippet_id=snippet_id,
            description=f"{snippet_id} description.",
            snippet_type=snippet_type,
            scope=scope,
            domain="general" if scope == "global" else "project",
            path=tmp_path / f"{snippet_id.replace('/', '_')}.md",
        )

    # Deliberately unsorted input spanning differing types and scopes, including
    # two same-(type, scope) entries to pin the ID tiebreak.
    principle_global_a = _meta("general/principle/aaa", "principle", "global")
    principle_global_b = _meta("general/principle/bbb", "principle", "global")
    principle_project = _meta("project/principle/zzz", "principle", "project")
    concept_global = _meta("general/concept/ccc", "concept", "global")
    policy_project = _meta("project/policy/ppp", "policy", "project")
    spec_global = _meta("general/spec/sss", "spec", "global")
    unordered = [
        spec_global,
        policy_project,
        principle_project,
        concept_global,
        principle_global_b,
        principle_global_a,
    ]

    output = _build_phase1_output(
        unordered,
        [],
        areas=[],
        test_agent=None,
        test_mode=None,
        test_request=None,
        test_csv_path=None,
    )

    expected_order = [
        principle_global_a,
        principle_global_b,
        principle_project,
        concept_global,
        policy_project,
        spec_global,
    ]
    positions = [output.index(snippet.snippet_id) for snippet in expected_order]
    assert positions == sorted(positions)


@pytest.mark.spec(_SPEC, "UC-3PR1")
def test_phase2_orders_resolved_snippets_by_taxonomy_type_then_id(tmp_path: Path) -> None:
    """Phase-2 renders the resolved snippets in taxonomy general-to-specific order, ID within a type."""
    docs_dir = tmp_path / "docs" / "project"

    def _entry(snippet_id: str, snippet_type: str) -> _IndexEntry:
        snippet_path = docs_dir / f"{snippet_id.replace('/', '_')}.md"
        snippet_path.parent.mkdir(parents=True, exist_ok=True)
        snippet_path.write_text(
            f"---\nid: {snippet_id}\ntype: {snippet_type}\ndomain: project\nscope: project\n"
            f"description: {snippet_id} snippet.\n---\n# {snippet_id}\n\nBody.\n",
            encoding="utf-8",
        )
        return {
            "id": snippet_id,
            "description": f"{snippet_id} snippet.",
            "type": snippet_type,
            "scope": "project",
            "domain": "project",
            "visibility": "public",
            "path": str(snippet_path.relative_to(tmp_path)),
        }

    # Two specs pin the ID tiebreak within a single taxonomy type.
    entries = [
        _entry("project/spec/feature/context/beta", "spec"),
        _entry("project/principle/core", "principle"),
        _entry("project/policy/rules", "policy"),
        _entry("project/concept/overview", "concept"),
        _entry("project/spec/feature/context/alpha", "spec"),
    ]
    index_path = docs_dir / "index.yaml"
    index_path.write_text(
        json.dumps({"project_root": str(tmp_path), "snippets": entries}, indent=2),
        encoding="utf-8",
    )

    output = build_context_output(
        areas=[],
        project_root=tmp_path,
        snippet_ids=[entry["id"] for entry in entries],
        target_slug=None,
    )

    # Each id is echoed in the "# Requested:" header and again in its rendered
    # block; rindex locates the body occurrence, so positions track block order.
    expected_order = [
        "project/principle/core",
        "project/concept/overview",
        "project/policy/rules",
        "project/spec/feature/context/alpha",
        "project/spec/feature/context/beta",
    ]
    positions = [output.rindex(snippet_id) for snippet_id in expected_order]
    assert positions == sorted(positions)


@pytest.mark.spec(_SPEC, "UC-3PR2")
def test_phase2_resolves_planned_change_lens_and_default_awareness(tmp_path: Path, snapshot: object) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "target-lens.md"
    _write_snippet(
        snippet_path,
        """# Live Parent

Before paragraph.

<!-- planned-change:planned-change-markers -->
Current bounded text.
<!-- change:planned-change-markers -->
Replacement bounded text.
<!-- /planned-change:planned-change-markers -->

After paragraph.
""",
    )
    _write_index(tmp_path, snippet_path, superseded_by=["planned-change-markers"])

    assert {
        "plain": _phase2_output(tmp_path, target_slug=None),
        "target": _phase2_output(tmp_path, target_slug="planned-change-markers"),
        "other_target": _phase2_output(tmp_path, target_slug="other-slug"),
    } == snapshot


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


_HANDLER_PROJECT_ID = "project/spec/feature/context/handler-thing"


def _setup_handler_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Wire a controlled project tree and stub the handler's invocation boundary."""

    gdocs = tmp_path / "ghome" / ".teleclaude" / "docs"
    gdocs.mkdir(parents=True, exist_ok=True)
    (gdocs / "index.yaml").write_text(
        json.dumps({"project_root": str(gdocs), "snippets": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("teleclaude.context_selector.GLOBAL_SNIPPETS_DIR", gdocs)

    project_root = tmp_path / "proj"
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    index_path = project_root / "docs" / "project" / "index.yaml"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    entry: _IndexEntry = {
        "id": _HANDLER_PROJECT_ID,
        "description": "Handler thing snippet.",
        "type": "spec",
        "scope": "project",
        "domain": "project",
        "visibility": "public",
        "path": "docs/project/spec/feature/context/handler-thing.md",
    }
    index_path.write_text(
        json.dumps({"project_root": str(project_root), "snippets": [entry]}, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(docs_handler, "resolve_invocation_project_root", lambda: project_root)
    monkeypatch.setattr(docs_handler, "load_app_config", lambda *_: None)
    monkeypatch.setattr(docs_handler, "read_current_session_email", lambda: None)
    return project_root


def test_index_invalid_scope_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An invalid --scope value fails loud with a non-zero exit (handler error-path, no spec scenario)."""
    _setup_handler_project(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _handle_docs_index(["--scope", "bogus"])

    assert exc.value.code == 1
    assert capsys.readouterr().out  # an error message is surfaced, not a silent exit


@pytest.mark.spec(_SPEC, "UC-3PR4")
def test_unknown_project_returns_empty_without_hard_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown --project slug yields an empty result on both index and get, without raising."""
    _setup_handler_project(tmp_path, monkeypatch)

    # index: the project snippet is dropped → not listed.
    _handle_docs_index(["--project", "does-not-exist"])
    assert _HANDLER_PROJECT_ID not in capsys.readouterr().out

    # get: the same flag drops the snippet; it is reported unresolved, never a crash.
    _handle_docs_get([_HANDLER_PROJECT_ID, "--project", "does-not-exist"])
    assert _HANDLER_PROJECT_ID in capsys.readouterr().out
