"""Test specifications for scripts/distribute.py — context-preservation marker wrapping.

Covers:
  R5 — Only the AGENTS.md master output is wrapped with context-preservation markers.
       Individual commands and skills must NOT be wrapped — markers at the final
       write boundary only, never inside serialization functions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import frontmatter
import pytest

# scripts/ is not a package; add repo root to sys.path for import
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import distribute
from scripts.distribute import (
    expand_exec_directives,
    transform_to_codex,
    transform_to_gemini,
    wrap_with_context_markers,
)

pytestmark = pytest.mark.unit

MARKER_START = "<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->"
MARKER_END = "<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->"


# ---------------------------------------------------------------------------
# R5 — wrap_with_context_markers helper contract
# ---------------------------------------------------------------------------


def test_markdown_wrapped_content_contains_start_marker() -> None:
    """wrap_with_context_markers adds the start marker to markdown output."""
    result = wrap_with_context_markers("# Hello\n\nBody.", is_markdown=True)

    assert MARKER_START in result


def test_markdown_wrapped_content_contains_end_marker() -> None:
    """wrap_with_context_markers adds the end marker to markdown output."""
    result = wrap_with_context_markers("# Hello\n\nBody.", is_markdown=True)

    assert MARKER_END in result


def test_start_marker_precedes_content_body() -> None:
    """Start marker must appear before the document body."""
    content = "# My Heading"
    result = wrap_with_context_markers(content, is_markdown=True)

    start_pos = result.index(MARKER_START)
    content_pos = result.index("# My Heading")
    assert start_pos < content_pos, "Start marker must precede the document body"


def test_end_marker_follows_content_body() -> None:
    """End marker must appear after the document body."""
    content = "# My Heading"
    result = wrap_with_context_markers(content, is_markdown=True)

    content_pos = result.index("# My Heading")
    end_pos = result.index(MARKER_END)
    assert content_pos < end_pos, "End marker must follow the document body"


def test_toml_content_not_wrapped_with_markers() -> None:
    """wrap_with_context_markers passes TOML content through unmodified."""
    toml_content = "description = \"\"\"A prompt.\"\"\"\nprompt = '''\nDo something.\n'''\n"
    result = wrap_with_context_markers(toml_content, is_markdown=False)

    assert MARKER_START not in result, "TOML output must not contain start marker"
    assert MARKER_END not in result, "TOML output must not contain end marker"


def test_original_content_preserved_inside_markers() -> None:
    """wrap_with_context_markers preserves the original body exactly and adds only the outer markers."""
    content = "# Title\n\nParagraph one.\n\nParagraph two.\n\n"
    result = wrap_with_context_markers(content, is_markdown=True)

    assert result == f"{MARKER_START}\n{content}{MARKER_END}\n", (
        "Markdown wrapping must preserve the original body exactly and add only the outer markers"
    )


# ---------------------------------------------------------------------------
# R5 — Distribution pipeline output for markdown vs TOML agents
# ---------------------------------------------------------------------------


def test_codex_transform_output_keeps_single_quoted_frontmatter_scalars() -> None:
    """transform_to_codex normalizes frontmatter scalar strings to single-quoted YAML."""
    post = frontmatter.loads("---\nname: test-cmd\ndescription: Test.\n---\nDo the thing.\n")
    output = transform_to_codex(post)

    assert "name: 'test-cmd'" in output
    assert "description: 'Test.'" in output


def test_gemini_transform_output_does_not_contain_preservation_markers() -> None:
    """Gemini TOML output from the distribution pipeline must NOT be wrapped.

    HTML comments are invalid TOML — this constraint must hold both before and after
    the markdown wrapping feature is implemented.
    """
    post = frontmatter.loads("---\nname: test-cmd\ndescription: Test.\n---\nDo the thing.\n")
    output = transform_to_gemini(post)

    assert MARKER_START not in output, "Gemini TOML output must not contain start marker"
    assert MARKER_END not in output, "Gemini TOML output must not contain end marker"


def test_expand_exec_directives_prepends_repo_venv_to_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_bin = str(tmp_path / ".venv" / "bin")
    repo_bin = str(_REPO_ROOT / ".venv" / "bin")

    def fake_run(_cmd: str, **kwargs: object) -> SimpleNamespace:
        env = kwargs.get("env")
        assert isinstance(env, dict)
        assert isinstance(env.get("PATH"), str)
        path_entries = env["PATH"].split(os.pathsep)
        assert path_entries[:2] == [project_bin, repo_bin]
        return SimpleNamespace(returncode=0, stdout="telec help", stderr="")

    monkeypatch.setattr(distribute.subprocess, "run", fake_run)

    rendered = expand_exec_directives("<!-- @exec: telec -h -->", project_root=tmp_path)

    assert "telec help" in rendered
