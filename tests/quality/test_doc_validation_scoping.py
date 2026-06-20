"""Functional test pinning doc validation scoping behavior.

Prevents the regression: a file-scoped lint run must validate only the
caller's docs and must not invoke repo-wide cross-ref validation. With
--all / full runs, both the malformed foreign doc and the resource-validation
step are active.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

import teleclaude.quality.lint as lint_module
from teleclaude.git import GIT_EXECUTABLE
from teleclaude.resource_validation import (
    clear_errors,
    get_errors,
    validate_all_snippets,
)

pytestmark = pytest.mark.functional

_RESOURCE_VALIDATION_ARG = "--skip-deploy"
_HOME_PATHS_STEP = "home_paths"
_REPO_WIDE_ARG = "--repo-wide"
_WORKING_TREE_FILES_ARG = "--working-tree-files"
_TRACKED_OFFENDER = Path("docs/offender.md")
_UNTRACKED_OFFENDER = Path(".temp/offender.md")

_GOOD_SNIPPET = """\
---
id: project/concept/doc-validation-scoping-test
type: concept
scope: project
description: Test fixture for doc validation scoping.
---

# Doc Validation Scoping Test — Concept

## What

This is a test fixture.

## Why

Used in functional tests for workspace-scoped doc validation.
"""

_MALFORMED_SNIPPET = """\
---
id: project/concept/malformed-test-doc
type: concept
scope: project
description: Malformed test fixture — missing H1 heading.
---

No H1 heading here — this file will fail snippet_missing_h1.

## What

Content exists but there is no H1.

## Why

Intentionally malformed to verify scoping skips foreign docs.
"""


_STRIPPED_CONCEPT_SNIPPET = """\
---
description: Test fixture for stripped classifier validation.
---

# Stripped Classifier Validation — Concept

## What

This is a test fixture.

## Why

Used in functional tests for stripped frontmatter validation.
"""

_PLANNED_CHANGE_CONCEPT_SNIPPET = """\
---
description: Planned-change validation fixture.
---

# Planned Change Validation — Concept

## What

This fixture carries planned-change marker structure.

{planned_change_block}

## Why

Used in functional tests for planned-change marker validation.
"""

_STRIPPED_POLICY_WITH_CONCEPT_SECTIONS = """\
---
description: Wrong section fixture.
---

# Wrong Section Fixture — Policy

## What

This section belongs to a concept, not a policy.

## Why

This section belongs to a concept, not a policy.
"""

_POLICY_SNIPPET_TEMPLATE = """\
---
description: H1 suffix validation fixture.
type: concept
---

# {title}

## Rules

This fixture defines a rule.

## Rationale

Used in functional tests for H1 suffix validation.

## Scope

Applies to this fixture.

## Enforcement

Validation reports malformed headings.

## Exceptions

None.
"""

_THIRD_PARTY_WITHOUT_CLASSIFIERS = """\
---
description: Vendor docs.
---

# Vendor Docs

## Sources

- https://example.com/docs
"""


def _setup_docs(base: Path) -> tuple[Path, Path]:
    """Return (good_path, malformed_path) under a minimal project docs root."""
    concept_dir = base / "docs" / "project" / "concept"
    concept_dir.mkdir(parents=True)
    good = concept_dir / "doc-validation-scoping-test.md"
    bad = concept_dir / "malformed-test-doc.md"
    good.write_text(_GOOD_SNIPPET, encoding="utf-8")
    bad.write_text(_MALFORMED_SNIPPET, encoding="utf-8")
    return good, bad


def _normalized_findings(base: Path) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for finding in get_errors():
        item = dict(finding)
        raw_path = item.get("path")
        if raw_path:
            item["path"] = str(Path(raw_path).relative_to(base))
        normalized.append(item)
    return normalized


def _run_git(project_root: Path, *args: str) -> None:
    subprocess.run(
        [GIT_EXECUTABLE, *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )


def _write_todos_db(project_root: Path, statuses: dict[str, str]) -> None:
    db_path = project_root / ".teleclaude" / "todos.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE todo ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE todo_state ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        for index, (slug, status) in enumerate(statuses.items(), start=1):
            row_id = f"todo-{index}"
            conn.execute(
                "INSERT INTO todo (id, slug, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (row_id, slug, status, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO todo_state (id, slug, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (row_id, slug, "{}", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()
    finally:
        conn.close()


class TestValidateAllSnippetsScoping:
    def test_scoped_call_ignores_foreign_malformed_snippet(self, tmp_path: Path) -> None:
        good, _ = _setup_docs(tmp_path)
        clear_errors()
        validate_all_snippets(tmp_path, paths=[good])
        assert not get_errors()

    def test_full_run_reports_malformed_snippet(self, tmp_path: Path) -> None:
        _, malformed = _setup_docs(tmp_path)
        clear_errors()
        validate_all_snippets(tmp_path)
        findings = get_errors()
        paths_with_errors = {f["path"] for f in findings}
        assert str(malformed) in paths_with_errors

    def test_stripped_classifier_frontmatter_validates_cleanly(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "concept" / "stripped-classifier-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(_STRIPPED_CONCEPT_SNIPPET, encoding="utf-8")

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert not get_errors()

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1")
    def test_valid_planned_change_markers_validate_cleanly(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""<!-- planned-change:planned-change-markers -->
Current body.
<!-- change:planned-change-markers -->
Replacement body.
<!-- /planned-change:planned-change-markers -->

```
<!-- planned-change:<slug> -->
Current body.
<!-- change:<slug> -->
Replacement body.
<!-- /planned-change:<slug> -->
```"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert not get_errors()

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1b")
    def test_inline_code_span_planned_change_examples_are_not_validated(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""`<!-- planned-change:BadSlug -->`
`<!-- change:BadSlug -->`
`<!-- /planned-change:BadSlug -->`

<!-- planned-change:BadSlug -->
Current body.
<!-- change:BadSlug -->
Replacement body.
<!-- /planned-change:BadSlug -->"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert _normalized_findings(tmp_path) == [
            {
                "code": "snippet_planned_change_marker_invalid",
                "marker": "<!-- planned-change:BadSlug -->",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "slug must be kebab-case",
            },
            {
                "code": "snippet_planned_change_marker_invalid",
                "marker": "<!-- change:BadSlug -->",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "slug must be kebab-case",
            },
            {
                "code": "snippet_planned_change_marker_invalid",
                "marker": "<!-- /planned-change:BadSlug -->",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "slug must be kebab-case",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1b")
    def test_full_run_reports_delivered_planned_change_marker_slug(self, tmp_path: Path) -> None:
        _write_todos_db(tmp_path, {"already-delivered": "delivered"})
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""<!-- planned-change:already-delivered -->
Current body.
<!-- change:already-delivered -->
Replacement body.
<!-- /planned-change:already-delivered -->"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path)

        assert _normalized_findings(tmp_path) == [
            {
                "code": "snippet_planned_marker_invalid_slug",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "todo is delivered, not in flight",
                "slug": "already-delivered",
            }
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1b")
    def test_full_run_accepts_active_planned_change_marker_slug(self, tmp_path: Path) -> None:
        _write_todos_db(tmp_path, {"active-owner": "active"})
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""<!-- planned-change:active-owner -->
Current body.
<!-- change:active-owner -->
Replacement body.
<!-- /planned-change:active-owner -->"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path)

        assert not get_errors()

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1b")
    def test_full_run_reports_removed_and_missing_planned_add_marker_slugs(self, tmp_path: Path) -> None:
        _write_todos_db(tmp_path, {"removed-owner": "removed"})
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""<!-- planned:removed-owner -->
Removed owner content.
<!-- /planned:removed-owner -->

<!-- planned:missing-owner -->
Missing owner content.
<!-- /planned:missing-owner -->"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path)

        assert _normalized_findings(tmp_path) == [
            {
                "code": "snippet_planned_marker_invalid_slug",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "todo is removed, not in flight",
                "slug": "removed-owner",
            },
            {
                "code": "snippet_planned_marker_invalid_slug",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "no such todo — check `telec history search missing-owner`; maybe authored ahead, renamed, or gone",
                "slug": "missing-owner",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1b")
    def test_marker_liveness_ignores_code_examples_but_reports_bare_marker(self, tmp_path: Path) -> None:
        _write_todos_db(tmp_path, {})
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""`<!-- planned:example-owner -->`
`delivered_by: [{slug}]`
  — in-context `<!-- planned:placeholder-owner -->` blocks for additions.

```
<!-- planned:another-example -->
Example content.
<!-- /planned:another-example -->
```

<!-- planned:bare-owner -->
Bare content.
<!-- /planned:bare-owner -->"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path)

        assert _normalized_findings(tmp_path) == [
            {
                "code": "snippet_planned_marker_invalid_slug",
                "path": "docs/project/concept/planned-change-validation.md",
                "reason": "no such todo — check `telec history search bare-owner`; maybe authored ahead, renamed, or gone",
                "slug": "bare-owner",
            }
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1b")
    def test_scoped_run_does_not_check_marker_slug_liveness(self, tmp_path: Path) -> None:
        _write_todos_db(tmp_path, {"already-delivered": "delivered"})
        snippet = tmp_path / "docs" / "project" / "concept" / "planned-change-validation.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(
                planned_change_block="""<!-- planned-change:already-delivered -->
Current body.
<!-- change:already-delivered -->
Replacement body.
<!-- /planned-change:already-delivered -->"""
            ),
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert not get_errors()

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV1")
    def test_malformed_planned_change_markers_report_validation_errors(self, tmp_path: Path, snapshot: object) -> None:
        fixtures = {
            "missing-close.md": """<!-- planned-change:planned-change-markers -->
Current body.
<!-- change:planned-change-markers -->
Replacement body.""",
            "mismatched-slug.md": """<!-- planned-change:planned-change-markers -->
Current body.
<!-- change:other-slug -->
Replacement body.
<!-- /planned-change:planned-change-markers -->""",
            "missing-separator.md": """<!-- planned-change:planned-change-markers -->
Current body.
<!-- /planned-change:planned-change-markers -->""",
            "invalid-slug.md": """<!-- planned-change:BadSlug -->
Current body.
<!-- change:BadSlug -->
Replacement body.
<!-- /planned-change:BadSlug -->""",
        }
        paths = []
        for filename, block in fixtures.items():
            snippet = tmp_path / "docs" / "project" / "concept" / filename
            snippet.parent.mkdir(parents=True, exist_ok=True)
            snippet.write_text(
                _PLANNED_CHANGE_CONCEPT_SNIPPET.format(planned_change_block=block),
                encoding="utf-8",
            )
            paths.append(snippet)

        clear_errors()
        validate_all_snippets(tmp_path, paths=paths)

        assert _normalized_findings(tmp_path) == snapshot

    def test_section_validation_uses_path_derived_type(self, tmp_path: Path, snapshot: object) -> None:
        snippet = tmp_path / "docs" / "project" / "policy" / "wrong-section-fixture.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(_STRIPPED_POLICY_WITH_CONCEPT_SECTIONS, encoding="utf-8")

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert _normalized_findings(tmp_path) == snapshot

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV2")
    def test_policy_h1_without_type_suffix_reports_validation_error(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "policy" / "unsuffixed-policy.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(_POLICY_SNIPPET_TEMPLATE.format(title="Unsuffixed Policy"), encoding="utf-8")

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        findings = _normalized_findings(tmp_path)
        assert findings == [
            {
                "code": "snippet_title_suffix_invalid",
                "path": "docs/project/policy/unsuffixed-policy.md",
                "reason": "first H1 must end with — Policy",
            }
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV2")
    def test_policy_h1_with_type_suffix_validates_cleanly(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "policy" / "suffixed-policy.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(_POLICY_SNIPPET_TEMPLATE.format(title="Suffixed Policy — Policy"), encoding="utf-8")

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert not get_errors()

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", "UC-SFV2")
    def test_companion_h1_suffix_uses_parent_derived_classification(self, tmp_path: Path) -> None:
        parent = tmp_path / "docs" / "project" / "policy" / "parent-policy.md"
        companion = tmp_path / "docs" / "project" / "policy" / "parent-policy.pending-change.md"
        parent.parent.mkdir(parents=True)
        parent.write_text(_POLICY_SNIPPET_TEMPLATE.format(title="Parent Policy — Policy"), encoding="utf-8")
        companion.write_text(_POLICY_SNIPPET_TEMPLATE.format(title="Parent Policy Draft"), encoding="utf-8")

        clear_errors()
        validate_all_snippets(tmp_path, paths=[companion])

        findings = _normalized_findings(tmp_path)
        assert findings == [
            {
                "code": "snippet_title_suffix_invalid",
                "path": "docs/project/policy/parent-policy.pending-change.md",
                "reason": "first H1 must end with — Policy",
            }
        ]

    def test_third_party_without_classifier_frontmatter_validates_cleanly(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "third-party" / "vendor.md"
        snippet.parent.mkdir(parents=True)
        snippet.write_text(_THIRD_PARTY_WITHOUT_CLASSIFIERS, encoding="utf-8")

        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])

        assert not get_errors()

    def test_baseline_dedup_uses_path_derived_ids(self, tmp_path: Path, snapshot: object) -> None:
        baseline = tmp_path / "docs" / "global" / "software-development" / "baseline.md"
        baseline.parent.mkdir(parents=True)
        baseline.write_text("@docs/global/software-development/concept/baseline-entry.md\n", encoding="utf-8")
        baseline_entry = tmp_path / "docs" / "global" / "software-development" / "concept" / "baseline-entry.md"
        baseline_entry.parent.mkdir(parents=True)
        baseline_entry.write_text(_STRIPPED_CONCEPT_SNIPPET, encoding="utf-8")
        procedure = tmp_path / "docs" / "global" / "software-development" / "procedure" / "runner.md"
        procedure.parent.mkdir(parents=True)
        procedure.write_text(
            """---
description: Runner.
needs_domain_baseline: true
---

# Runner — Procedure

## Required reads

- @docs/global/software-development/concept/baseline-entry.md

## Goal

Run.

## Preconditions

Ready.

## Steps

Run.

## Outputs

Done.

## Recovery

Retry.
""",
            encoding="utf-8",
        )

        clear_errors()
        validate_all_snippets(tmp_path)

        assert _normalized_findings(tmp_path) == snapshot


_UC_SFV1C = "UC-SFV1c"


class TestMarkerStructureValidation:
    """In-body markers must be whole-line, non-nested, balanced, kebab.

    Binds to the validator's accepted grammar equalling the delivery fold's
    resolvable grammar (UC-SFV1c).
    """

    def _validate_block(self, tmp_path: Path, block: str) -> list[dict[str, str]]:
        snippet = tmp_path / "docs" / "project" / "concept" / "marker-structure.md"
        snippet.parent.mkdir(parents=True, exist_ok=True)
        snippet.write_text(
            _PLANNED_CHANGE_CONCEPT_SNIPPET.format(planned_change_block=block),
            encoding="utf-8",
        )
        clear_errors()
        validate_all_snippets(tmp_path, paths=[snippet])
        return _normalized_findings(tmp_path)

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_inline_planned_change_markers_are_line_level_findings(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "Before <!-- planned-change:inline-pc -->current<!-- change:inline-pc -->"
            "replacement<!-- /planned-change:inline-pc --> after.",
        )
        assert findings == [
            {
                "code": "snippet_marker_not_line_level",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned-change:inline-pc -->",
            },
            {
                "code": "snippet_marker_not_line_level",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- change:inline-pc -->",
            },
            {
                "code": "snippet_marker_not_line_level",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- /planned-change:inline-pc -->",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_inline_planned_add_markers_are_line_level_findings(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "Before <!-- planned:inline-add -->added<!-- /planned:inline-add --> after.",
        )
        assert findings == [
            {
                "code": "snippet_marker_not_line_level",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned:inline-add -->",
            },
            {
                "code": "snippet_marker_not_line_level",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- /planned:inline-add -->",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_non_kebab_planned_add_slug_is_a_finding(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "<!-- planned:Bad_Slug -->\nadded content\n<!-- /planned:Bad_Slug -->",
        )
        assert findings == [
            {
                "code": "snippet_marker_invalid_slug",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned:Bad_Slug -->",
                "reason": "slug must be kebab-case",
            },
            {
                "code": "snippet_marker_invalid_slug",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- /planned:Bad_Slug -->",
                "reason": "slug must be kebab-case",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_planned_change_nested_in_planned_change_is_a_finding(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "<!-- planned-change:outer -->\ncurrent-outer\n"
            "<!-- planned-change:inner -->\ncurrent-inner\n<!-- change:inner -->\n"
            "replacement-inner\n<!-- /planned-change:inner -->\n"
            "<!-- change:outer -->\nreplacement-outer\n<!-- /planned-change:outer -->",
        )
        assert findings == [
            {
                "code": "snippet_marker_nested",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned-change:inner -->",
                "enclosing": "<!-- planned-change:outer -->",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_planned_add_nested_in_planned_add_is_a_finding(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "<!-- planned:outer -->\nouter content\n"
            "<!-- planned:inner -->\ninner content\n<!-- /planned:inner -->\n"
            "<!-- /planned:outer -->",
        )
        assert findings == [
            {
                "code": "snippet_marker_nested",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned:inner -->",
                "enclosing": "<!-- planned:outer -->",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_unclosed_planned_add_block_is_unbalanced(self, tmp_path: Path) -> None:
        findings = self._validate_block(tmp_path, "<!-- planned:lonely -->\norphaned content")
        assert findings == [
            {
                "code": "snippet_marker_unbalanced",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned:lonely -->",
                "reason": "block is never closed",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_orphan_planned_close_is_unbalanced(self, tmp_path: Path) -> None:
        findings = self._validate_block(tmp_path, "<!-- /planned:orphan -->")
        assert findings == [
            {
                "code": "snippet_marker_unbalanced",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- /planned:orphan -->",
                "reason": "closing marker has no matching open block",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_mismatched_planned_close_slug_is_unbalanced(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "<!-- planned:slug-a -->\ncontent\n<!-- /planned:slug-b -->",
        )
        assert findings == [
            {
                "code": "snippet_marker_unbalanced",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- /planned:slug-b -->",
                "reason": "closing marker has no matching open block",
            },
            {
                "code": "snippet_marker_unbalanced",
                "path": "docs/project/concept/marker-structure.md",
                "marker": "<!-- planned:slug-a -->",
                "reason": "block is never closed",
            },
        ]

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_own_line_non_nested_balanced_markers_validate_cleanly(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "<!-- planned:add-slug -->\nadded content\n<!-- /planned:add-slug -->\n\n"
            "<!-- planned-change:change-slug -->\ncurrent\n<!-- change:change-slug -->\n"
            "replacement\n<!-- /planned-change:change-slug -->",
        )
        assert findings == []

    @pytest.mark.spec("project/spec/feature/context/snippet-frontmatter-validation", _UC_SFV1C)
    def test_markers_inside_code_fence_are_not_flagged(self, tmp_path: Path) -> None:
        findings = self._validate_block(
            tmp_path,
            "```\n<!-- planned:Bad_Slug -->\ninline <!-- planned-change:Also_Bad --> example\n```",
        )
        assert findings == []


class TestLintPipelineDocValidationScoping:
    def test_file_scoped_run_skips_resource_validation_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good, _ = _setup_docs(tmp_path)
        invocations: list[list[str]] = []

        def fake_run(cmd: list[str], *_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            invocations.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr(lint_module, "_pipeline_ctx", [tmp_path])

        lint_module.run_pipeline([str(good)], run_all=False)

        sync_calls = [cmd for cmd in invocations if _RESOURCE_VALIDATION_ARG in cmd]
        assert not sync_calls, f"telec sync must not run on file-scoped run, got: {sync_calls}"

    def test_full_run_invokes_resource_validation_step(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        good, _ = _setup_docs(tmp_path)
        invocations: list[list[str]] = []

        def fake_run(cmd: list[str], *_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            invocations.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr(lint_module, "_pipeline_ctx", [tmp_path])

        lint_module.run_pipeline([str(good)], run_all=True)

        sync_calls = [cmd for cmd in invocations if _RESOURCE_VALIDATION_ARG in cmd]
        assert sync_calls, f"telec sync must run on full run, got invocations: {invocations}"

    def test_full_run_invokes_home_paths_repo_wide_without_file_operands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invocations: list[tuple[str, list[str]]] = []

        def fake_run_tool(cmd: list[str], _project_root: Path, step_name: str) -> None:
            invocations.append((step_name, list(cmd)))

        monkeypatch.setattr(lint_module, "_run_tool", fake_run_tool)
        monkeypatch.setattr(lint_module, "_pipeline_ctx", [tmp_path])

        lint_module.run_pipeline([], run_all=True)

        home_paths_commands = [cmd for step_name, cmd in invocations if step_name == _HOME_PATHS_STEP]
        assert len(home_paths_commands) == 1
        home_paths_command = home_paths_commands[0]
        assert _REPO_WIDE_ARG in home_paths_command
        assert _WORKING_TREE_FILES_ARG not in home_paths_command
        assert home_paths_command[-1] == _REPO_WIDE_ARG

    def test_full_run_home_paths_scans_tracked_markdown_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracked = tmp_path / _TRACKED_OFFENDER
        tracked.parent.mkdir(parents=True)
        tracked.write_text("/Users/Morriz/.teleclaude/docs/general/spec/tools/telec-cli.md\n", encoding="utf-8")
        untracked = tmp_path / _UNTRACKED_OFFENDER
        untracked.parent.mkdir(parents=True)
        untracked.write_text("/Users/Morriz/.teleclaude/docs/general/spec/tools/telec-cli.md\n", encoding="utf-8")
        _run_git(tmp_path, "init")
        _run_git(tmp_path, "add", _TRACKED_OFFENDER.as_posix())
        home_paths_results: list[subprocess.CompletedProcess[str]] = []

        def fake_run_tool(cmd: list[str], project_root: Path, step_name: str) -> None:
            if step_name != _HOME_PATHS_STEP:
                return
            result = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            home_paths_results.append(result)
            if result.returncode != 0:
                raise SystemExit(result.returncode)

        monkeypatch.setattr(lint_module, "_run_tool", fake_run_tool)
        monkeypatch.setattr(lint_module, "_pipeline_ctx", [tmp_path])

        with pytest.raises(SystemExit) as exc_info:
            lint_module.run_pipeline([], run_all=True)

        assert exc_info.value.code == 1
        assert len(home_paths_results) == 1
        result = home_paths_results[0]
        assert result.returncode == 1
        assert [Path(line) for line in result.stdout.splitlines()] == [_TRACKED_OFFENDER]
