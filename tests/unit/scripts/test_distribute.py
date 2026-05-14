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

_SNAPSHOT_DIR = Path(__file__).with_name("__snapshots__") / "test_distribute"


def _assert_text_snapshot(name: str, content: str) -> None:
    expected = (_SNAPSHOT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    if expected.endswith("\n") and not content.endswith("\n"):
        expected = expected[:-1]
    assert content == expected


# ---------------------------------------------------------------------------
# R5 — wrap_with_context_markers helper contract
# ---------------------------------------------------------------------------


def test_markdown_wrapped_content_matches_snapshot() -> None:
    """wrap_with_context_markers wraps markdown at the final write boundary."""
    result = wrap_with_context_markers("# Hello\n\nBody.", is_markdown=True)

    _assert_text_snapshot("markdown_wrapped_content", result)


def test_toml_content_passthrough_matches_snapshot() -> None:
    """wrap_with_context_markers passes non-markdown content through unmodified."""
    toml_content = "description = \"\"\"A prompt.\"\"\"\nprompt = '''\nDo something.\n'''\n"
    result = wrap_with_context_markers(toml_content, is_markdown=False)

    _assert_text_snapshot("toml_content_passthrough", result)


# ---------------------------------------------------------------------------
# R5 — Distribution pipeline output for markdown vs TOML agents
# ---------------------------------------------------------------------------


def test_codex_transform_output_matches_snapshot() -> None:
    """transform_to_codex normalizes frontmatter scalar strings to single-quoted YAML."""
    post = frontmatter.loads("---\nname: test-cmd\ndescription: Test.\n---\nDo the thing.\n")
    output = transform_to_codex(post)

    _assert_text_snapshot("codex_transform_output", output)


def test_gemini_transform_output_matches_snapshot() -> None:
    """Gemini TOML output from the distribution pipeline is not markdown-wrapped."""
    post = frontmatter.loads("---\nname: test-cmd\ndescription: Test.\n---\nDo the thing.\n")
    output = transform_to_gemini(post)

    _assert_text_snapshot("gemini_transform_output", output)


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

    _assert_text_snapshot("exec_directive_expansion", rendered)
