"""Functional coverage for home-path guardrail filtering."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.lint import home_paths

_SPEC = "general/spec/tools/telec-cli"


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_home_paths_allows_smudged_resource_refs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    ref = docs / "ref.md"
    ref.write_text("@/Users/Morriz/.teleclaude/docs/general/spec/tools/telec-cli.md\n", encoding="utf-8")

    result = home_paths.main(["--project-root", str(tmp_path), "--working-tree-files", "docs/ref.md"])

    captured = capsys.readouterr()
    assert result == 0
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_home_paths_rejects_bare_home_refs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    ref = docs / "ref.md"
    ref.write_text("/Users/Morriz/.teleclaude/docs/general/spec/tools/telec-cli.md\n", encoding="utf-8")

    result = home_paths.main(["--project-root", str(tmp_path), "--working-tree-files", "docs/ref.md"])

    captured = capsys.readouterr()
    assert result == 1
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot
