"""Functional test pinning doc validation scoping behavior.

Prevents the regression: a file-scoped lint run must validate only the
caller's docs and must not invoke repo-wide cross-ref validation. With
--all / full runs, both the malformed foreign doc and the resource-validation
step are active.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import teleclaude.quality.lint as lint_module
from teleclaude.resource_validation import (
    clear_errors,
    get_errors,
    validate_all_snippets,
)

pytestmark = pytest.mark.functional

_RESOURCE_VALIDATION_ARG = "--skip-deploy"

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
