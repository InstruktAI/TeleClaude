"""Behavioral specs for artifact section-order validation.

Commands may carry an ordered subset of the canonical sections so thin wrappers
stay minimal; other artifact kinds must match the full schema exactly. Order is
always enforced.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from teleclaude.resource_validation import _validate_artifact_section_order, validate_artifact

pytestmark = pytest.mark.unit


def _check(body: str, *, kind: str) -> None:
    lines = body.splitlines()
    _validate_artifact_section_order(lines, "artifact.md", kind=kind, h1_idx=0)


def _command_post(steps_body: str) -> frontmatter.Post:
    return frontmatter.loads(
        "---\ndescription: Test command\n---\n# Title\n\nYou are now the Tester.\n\n"
        f"## Purpose\n\nx\n\n## Steps\n\n{steps_body}\n"
    )


def test_command_accepts_thin_purpose_and_steps_subset() -> None:
    """A wrapper with only Purpose and Steps validates — sections may be omitted."""
    _check("# Title\n\n## Purpose\n\nx\n\n## Steps\n\nFollow the procedure.\n", kind="command")


def test_command_rejects_sections_out_of_canonical_order() -> None:
    """Present sections must keep the canonical order even when some are omitted."""
    with pytest.raises(ValueError):
        _check("# Title\n\n## Steps\n\ny\n\n## Purpose\n\nx\n", kind="command")


def test_command_rejects_duplicate_section() -> None:
    """A section repeated cannot map onto the single canonical slot."""
    with pytest.raises(ValueError):
        _check("# Title\n\n## Steps\n\na\n\n## Steps\n\nb\n", kind="command")


def test_command_rejects_unknown_section() -> None:
    """A heading outside the canonical set is rejected regardless of order."""
    with pytest.raises(ValueError):
        _check("# Title\n\n## Purpose\n\nx\n\n## Notes\n\ny\n", kind="command")


def test_non_command_still_requires_full_schema() -> None:
    """Agents must carry the complete section set; subsets are rejected."""
    with pytest.raises(ValueError):
        _check("# Title\n\n## Purpose\n\nx\n\n## Procedure\n\ny\n", kind="agent")


def test_validate_artifact_accepts_existing_include_target(tmp_path: Path) -> None:
    """A body @include whose target exists passes validation."""
    snippet = tmp_path / "docs" / "snippets" / "ok.md"
    snippet.parent.mkdir(parents=True, exist_ok=True)
    snippet.write_text("## Rules\n\nResolve the slug.\n", encoding="utf-8")
    post = _command_post("<!-- @include: docs/snippets/ok.md -->\n\nFollow the procedure.")

    validate_artifact(post, str(tmp_path / "cmd.md"), kind="command", project_root=tmp_path)


def test_validate_artifact_rejects_missing_include_target(tmp_path: Path) -> None:
    """A body @include whose target is missing fails validation — caught before distribution."""
    post = _command_post("<!-- @include: docs/snippets/missing.md -->\n\nFollow the procedure.")

    with pytest.raises(ValueError):
        validate_artifact(post, str(tmp_path / "cmd.md"), kind="command", project_root=tmp_path)
