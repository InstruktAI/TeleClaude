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
from syrupy.assertion import SnapshotAssertion

# scripts/ is not a package; add repo root to sys.path for import
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import distribute
from scripts.distribute import (
    _inflate_domain_baseline,
    expand_exec_directives,
    expand_inline_refs,
    transform_to_codex,
    transform_to_gemini,
    wrap_with_context_markers,
)

pytestmark = pytest.mark.unit

# Snippet ids used by the inline-expansion fixtures. Named constants stand in for
# protocol identity rather than inlining the strings at assertion sites.
_POLICY_A_ID = "test/policy/a"
_POLICY_B_ID = "test/policy/b"


def _write_snippet(root: Path, rel: str, snippet_id: str, body: str) -> None:
    """Write a frontmatter snippet with an ``id`` under ``root``."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {snippet_id}\ntype: policy\n---\n{body}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# R5 — wrap_with_context_markers helper contract
# ---------------------------------------------------------------------------


def test_markdown_wrapped_content_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    """wrap_with_context_markers wraps markdown at the final write boundary."""
    result = wrap_with_context_markers("# Hello\n\nBody.", is_markdown=True)

    assert result == snapshot


def test_toml_content_passthrough_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    """wrap_with_context_markers passes non-markdown content through unmodified."""
    toml_content = "description = \"\"\"A prompt.\"\"\"\nprompt = '''\nDo something.\n'''\n"
    result = wrap_with_context_markers(toml_content, is_markdown=False)

    assert result == snapshot


# ---------------------------------------------------------------------------
# R5 — Distribution pipeline output for markdown vs TOML agents
# ---------------------------------------------------------------------------


def test_codex_transform_output_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    """transform_to_codex normalizes frontmatter scalar strings to single-quoted YAML."""
    post = frontmatter.loads("---\nname: test-cmd\ndescription: Test.\n---\nDo the thing.\n")
    output = transform_to_codex(post)

    assert output == snapshot


def test_gemini_transform_output_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    """Gemini TOML output from the distribution pipeline is not markdown-wrapped."""
    post = frontmatter.loads("---\nname: test-cmd\ndescription: Test.\n---\nDo the thing.\n")
    output = transform_to_gemini(post)

    assert output == snapshot


def test_expand_exec_directives_prepends_repo_venv_to_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
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

    assert rendered == snapshot


# ---------------------------------------------------------------------------
# Inline expansion + domain baseline inflation
# ---------------------------------------------------------------------------


def test_expand_inline_refs_inlines_referenced_snippet_transitively(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """A required-read procedure and the snippet it transitively @-refs are both inlined."""
    _write_snippet(tmp_path, "docs/policy-a.md", _POLICY_A_ID, "# Policy A\n\nAlpha rule.")
    (tmp_path / "docs" / "proc.md").write_text(
        "---\nid: test/procedure/proc\ntype: procedure\n---\n# Proc\n\nProcedure body.\n\n@docs/policy-a.md\n",
        encoding="utf-8",
    )
    content = "# Command\n\n## Required reads\n\n- @docs/proc.md\n\n## Body\n\nCommand body.\n"

    result = expand_inline_refs(content, project_root=tmp_path, current_path=tmp_path / "cmd.md")

    assert result == snapshot


def test_inflate_domain_baseline_appends_progressive_index(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    """The baseline inflation appends the sibling progressive catalogue when present."""
    domain_src = tmp_path / "docs" / "global" / "widgets"
    _write_snippet(tmp_path, "docs/global/widgets/policy-a.md", _POLICY_A_ID, "# Policy A\n\nAlpha rule.")
    _write_snippet(tmp_path, "docs/global/widgets/policy-b.md", _POLICY_B_ID, "# Policy B\n\nBeta rule.")
    (domain_src / "baseline.md").write_text("@docs/global/widgets/policy-a.md\n", encoding="utf-8")
    (domain_src / "baseline-progressive.md").write_text("@docs/global/widgets/policy-b.md\n", encoding="utf-8")

    result = _inflate_domain_baseline(domain_src / "baseline.md", domain_src, project_root=tmp_path)

    assert result == snapshot


def test_inflate_domain_baseline_without_progressive_sibling(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    """With no progressive sibling, the inflation is the baseline content alone."""
    domain_src = tmp_path / "docs" / "global" / "widgets"
    _write_snippet(tmp_path, "docs/global/widgets/policy-a.md", _POLICY_A_ID, "# Policy A\n\nAlpha rule.")
    (domain_src / "baseline.md").write_text("@docs/global/widgets/policy-a.md\n", encoding="utf-8")

    result = _inflate_domain_baseline(domain_src / "baseline.md", domain_src, project_root=tmp_path)

    assert result == snapshot
