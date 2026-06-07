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

_RESOURCE_VALIDATION_ARG = "--validate-only"

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


def _setup_docs(base: Path) -> tuple[Path, Path]:
    """Return (good_path, malformed_path) under a minimal project docs root."""
    concept_dir = base / "docs" / "project" / "concept"
    concept_dir.mkdir(parents=True)
    good = concept_dir / "doc-validation-scoping-test.md"
    bad = concept_dir / "malformed-test-doc.md"
    good.write_text(_GOOD_SNIPPET, encoding="utf-8")
    bad.write_text(_MALFORMED_SNIPPET, encoding="utf-8")
    return good, bad


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
