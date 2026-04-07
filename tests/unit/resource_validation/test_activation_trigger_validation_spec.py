# guard: no-companion
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# pylint: disable=import-outside-toplevel
"""Test spec for R2: ``activation_trigger`` frontmatter field validation.

Procedure snippets may declare an optional ``activation_trigger`` field.
Validation must:
- Accept ``activation_trigger`` on procedure snippets (non-empty string).
- Reject ``activation_trigger`` on any non-procedure snippet type.
- Reject empty string values.
- Reject non-string values.

These tests document the behavioral contract that the implementation must
preserve.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


def _make_snippet(
    tmp_path: Path, *, snippet_type: str, activation_trigger: str | int | None = None
) -> tuple[Path, str]:
    """Build a minimal snippet file with frontmatter and return (path, content).

    Places the file under the correct taxonomy path so ``validate_snippet``
    can infer the type from the directory structure.
    """
    domain = "general" if snippet_type in {"procedure", "principle", "concept"} else "software-development"
    snippet_dir = tmp_path / "docs" / "global" / domain / snippet_type
    snippet_dir.mkdir(parents=True, exist_ok=True)
    snippet_path = snippet_dir / "test-snippet.md"

    fm_lines = [
        "---",
        f"id: {domain}/{snippet_type}/test-snippet",
        f"type: {snippet_type}",
        f"domain: {domain}",
        "description: Test snippet for activation_trigger validation",
    ]
    if activation_trigger is not None:
        if isinstance(activation_trigger, str):
            fm_lines.append(f'activation_trigger: "{activation_trigger}"')
        else:
            fm_lines.append(f"activation_trigger: {activation_trigger}")
    fm_lines.append("---")

    body = dedent("""\
        # Test Snippet — {type_title}

        ## Required reads

        ## Rules

        Test content.
    """).format(type_title=snippet_type.title())

    content = "\n".join(fm_lines) + "\n" + body
    snippet_path.write_text(content, encoding="utf-8")
    return snippet_path, content


class TestActivationTriggerAcceptedOnProcedure:
    """R2: ``activation_trigger`` is valid on procedure snippets."""

    def test_procedure_with_valid_activation_trigger_produces_no_error(self, tmp_path: Path) -> None:
        """A procedure snippet with a non-empty string ``activation_trigger`` passes validation."""
        from teleclaude.resource_validation import _models as m
        from teleclaude.resource_validation._snippet import validate_snippet

        m.clear_errors()

        path, content = _make_snippet(
            tmp_path,
            snippet_type="procedure",
            activation_trigger="Use when the user wants to brainstorm",
        )

        validate_snippet(path, content, tmp_path, domains={"general", "software-development"})

        errors = m.get_errors()
        trigger_errors = [e for e in errors if "activation_trigger" in e.get("code", "")]
        assert trigger_errors == [], (
            f"Valid activation_trigger on procedure should produce no errors, got: {trigger_errors}"
        )

        m.clear_errors()


class TestActivationTriggerRejectedOnNonProcedure:
    """R2: ``activation_trigger`` is rejected on non-procedure snippet types."""

    @pytest.mark.parametrize("snippet_type", ["policy", "spec", "principle", "concept", "design"])
    def test_non_procedure_with_activation_trigger_produces_error(self, tmp_path: Path, snippet_type: str) -> None:
        """Non-procedure snippet types must not declare ``activation_trigger``."""
        from teleclaude.resource_validation import _models as m
        from teleclaude.resource_validation._snippet import validate_snippet

        m.clear_errors()

        path, content = _make_snippet(
            tmp_path,
            snippet_type=snippet_type,
            activation_trigger="Should not be here",
        )

        validate_snippet(path, content, tmp_path, domains={"general", "software-development"})

        errors = m.get_errors()
        trigger_errors = [e for e in errors if "activation_trigger" in e.get("code", "")]
        assert len(trigger_errors) >= 1, f"activation_trigger on {snippet_type} should produce a validation error"

        m.clear_errors()


class TestActivationTriggerRejectedOnInvalidValues:
    """R2: ``activation_trigger`` must be a non-empty string."""

    def test_empty_string_activation_trigger_produces_error(self, tmp_path: Path) -> None:
        """An empty string ``activation_trigger`` is rejected."""
        from teleclaude.resource_validation import _models as m
        from teleclaude.resource_validation._snippet import validate_snippet

        m.clear_errors()

        path, content = _make_snippet(
            tmp_path,
            snippet_type="procedure",
            activation_trigger="",
        )

        validate_snippet(path, content, tmp_path, domains={"general", "software-development"})

        errors = m.get_errors()
        trigger_errors = [e for e in errors if "activation_trigger" in e.get("code", "")]
        assert len(trigger_errors) >= 1, "Empty activation_trigger should produce a validation error"

        m.clear_errors()

    def test_non_string_activation_trigger_produces_error(self, tmp_path: Path) -> None:
        """A non-string ``activation_trigger`` value (e.g., integer) is rejected."""
        from teleclaude.resource_validation import _models as m
        from teleclaude.resource_validation._snippet import validate_snippet

        m.clear_errors()

        path, content = _make_snippet(
            tmp_path,
            snippet_type="procedure",
            activation_trigger=42,
        )

        validate_snippet(path, content, tmp_path, domains={"general", "software-development"})

        errors = m.get_errors()
        trigger_errors = [e for e in errors if "activation_trigger" in e.get("code", "")]
        assert len(trigger_errors) >= 1, "Non-string activation_trigger should produce a validation error"

        m.clear_errors()
