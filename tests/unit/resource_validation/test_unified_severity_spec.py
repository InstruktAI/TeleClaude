# guard: no-companion
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, reportUnknownLambdaType=false
# pylint: disable=import-outside-toplevel,protected-access,too-few-public-methods
"""Test spec for R1: Unified validation severity.

The resource validation pipeline must use a single severity level for all
findings. The dual warn/error distinction is removed — all findings are errors.
The ``--warn-only`` flag controls whether collected findings block sync, not
severity category.

Adaptation notes for existing tests that will break under R1:

- ``test__models.py::TestWarningAndErrorCollection.test_warn_and_error_are_collected_and_clearable``
  Calls ``_warn()``, ``_error()``, ``clear_warnings()``, ``get_warnings()``,
  ``get_errors()`` — the old dual-severity API. Must be adapted to the unified
  API during the build phase.

- ``test__snippet.py::TestThirdPartyValidation.test_warns_for_non_url_source_entries``
  Calls ``resource_models.clear_warnings()`` and asserts ``resource_models.get_warnings()``.
  Must switch to ``get_errors()`` / ``clear_errors()`` during the build phase.

- ``test_sync.py::TestPrintWarnings.test_groups_warnings_by_code_and_reason``
  Prose-lock: ``assert "Validation warnings: 2" in output``. Must be replaced
  with a behavioral assertion (e.g., function return value or structured data)
  during the build phase.

- ``tests/unit/project_setup/test_sync.py::test_sync_project_artifacts_prints_warning_when_sync_reports_false``
  Prose-lock: ``assert "sync completed with warnings" in capsys.readouterr().out``.
  Must be replaced with a behavioral assertion during the build phase.

These tests document the behavioral contract that the implementation must
preserve.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestUnifiedSeverityAPI:
    """R1: The module exposes a single collection, retrieval, and clear function."""

    def test_error_function_records_findings(self) -> None:
        """Single collection function records validation findings as errors."""
        from teleclaude.resource_validation import _models as m

        m.clear_errors()

        m._error("test_code", path="docs/a.md", reason="test")

        findings = m.get_errors()
        assert len(findings) == 1
        assert findings[0]["code"] == "test_code"
        assert findings[0]["path"] == "docs/a.md"
        assert findings[0]["reason"] == "test"

        m.clear_errors()

    def test_clear_errors_empties_collection(self) -> None:
        """Single clear function empties the findings collection."""
        from teleclaude.resource_validation import _models as m

        m.clear_errors()
        m._error("code_a", path="docs/a.md")
        m._error("code_b", path="docs/b.md")

        assert len(m.get_errors()) == 2

        m.clear_errors()

        assert not m.get_errors()

    def test_get_errors_returns_copy(self) -> None:
        """Retrieval function returns a copy, not a reference to internal state."""
        from teleclaude.resource_validation import _models as m

        m.clear_errors()
        m._error("code_x", path="docs/x.md")

        result = m.get_errors()
        result.clear()

        assert len(m.get_errors()) == 1

        m.clear_errors()

    def test_extra_kwargs_preserved_in_findings(self) -> None:
        """Arbitrary keyword arguments are preserved in the finding dict."""
        from teleclaude.resource_validation import _models as m

        m.clear_errors()
        m._error("ref_broken", path="docs/a.md", ref="@docs/b.md", resolved="/tmp/b.md")

        finding = m.get_errors()[0]
        assert finding["ref"] == "@docs/b.md"
        assert finding["resolved"] == "/tmp/b.md"

        m.clear_errors()


class TestWarningAPIRemoved:
    """R1: The old dual-severity warning functions no longer exist."""

    def test_warn_function_removed(self) -> None:
        """``_warn()`` is no longer exposed — all findings use ``_error()``."""
        from teleclaude.resource_validation import _models as m

        assert not hasattr(m, "_warn"), "_warn should be removed; all findings are errors"

    def test_get_warnings_removed(self) -> None:
        """``get_warnings()`` is no longer exposed."""
        from teleclaude.resource_validation import _models as m

        assert not hasattr(m, "get_warnings"), "get_warnings should be removed"

    def test_get_warnings_removed_from_package(self) -> None:
        """``get_warnings()`` is no longer re-exported from the package surface."""
        import teleclaude.resource_validation as rv

        assert not hasattr(rv, "get_warnings"), "resource_validation must not expose get_warnings"

    def test_clear_warnings_removed(self) -> None:
        """``clear_warnings()`` is no longer exposed — use ``clear_errors()``."""
        from teleclaude.resource_validation import _models as m

        assert not hasattr(m, "clear_warnings"), "clear_warnings should be removed; use clear_errors"


class TestThirdPartyValidationUsesErrors:
    """R1 adaptation: third-party validation reports errors, not warnings.

    Replacement spec for F-03 (test__snippet.py::TestThirdPartyValidation).
    """

    def test_non_url_source_reported_as_error(self, tmp_path: Path) -> None:
        """Invalid third-party sources produce error findings, not warnings."""
        from teleclaude.resource_validation import _models as resource_models
        from teleclaude.resource_validation import _snippet

        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text(
            "# Guide\n\n## Sources\n- not-a-url\n- /context7/library\n- https://example.com\n",
            encoding="utf-8",
        )

        _snippet.validate_third_party_docs(tmp_path)

        errors = resource_models.get_errors()
        assert len(errors) == 1
        assert errors[0]["code"] == "third_party_source_invalid"
        assert errors[0]["path"] == str(doc_path)
        assert errors[0]["source"] == "not-a-url"

        resource_models.clear_errors()


class TestSyncWarnOnlyLeniencyPreserved:
    """R1: ``--warn-only`` controls whether findings block sync, not severity.

    Replacement spec for F-06 prose-lock assertions in sync tests. Asserts
    behavioral return values instead of rendered output text.
    """

    def test_sync_returns_true_with_warn_only_despite_findings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When ``warn_only=True``, sync returns True even if findings exist."""
        from teleclaude import sync
        from teleclaude.resource_validation import _models as m

        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _pr: None)
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _pr: None)
        monkeypatch.setattr(sync, "validate_third_party_docs", lambda _pr: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _pr: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _pr: [])
        monkeypatch.setattr(sync, "build_all_indexes", lambda _pr: [])
        monkeypatch.setattr(sync, "_register_project_manifest", lambda _pr: None)
        monkeypatch.setattr(sync, "_run_distribute", lambda _pr, **_kw: None)

        m.clear_errors()

        def inject_finding(_pr: Path) -> None:
            m._error("test_finding", path="docs/test.md")

        monkeypatch.setattr(sync, "validate_all_snippets", inject_finding)

        result = sync.sync(tmp_path, warn_only=True)

        assert result is True, "warn_only=True should not block sync"

        m.clear_errors()

    def test_sync_returns_false_without_warn_only_when_findings_exist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When ``warn_only=False``, sync returns False if findings exist."""
        from teleclaude import sync
        from teleclaude.resource_validation import _models as m

        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _pr: None)
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _pr: None)
        monkeypatch.setattr(sync, "validate_third_party_docs", lambda _pr: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _pr: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _pr: [])

        m.clear_errors()

        def inject_finding(_pr: Path) -> None:
            m._error("test_finding", path="docs/test.md")

        monkeypatch.setattr(sync, "validate_all_snippets", inject_finding)

        result = sync.sync(tmp_path, validate_only=True, warn_only=False)

        assert result is False, "warn_only=False should block sync when findings exist"

        m.clear_errors()
