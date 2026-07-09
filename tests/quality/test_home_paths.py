"""Functional coverage for home-path guardrail filtering."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.lint import home_paths

_SPEC = "general/spec/tools/telec-cli"


def _run_git(project_root: Path, *args: str) -> None:
    result = subprocess.run(
        [home_paths.GIT_EXECUTABLE, *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _init_repo_with_tracked_doc(project_root: Path, relative_path: str, content: str) -> None:
    path = project_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _run_git(project_root, "init")
    _run_git(project_root, "add", relative_path)


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


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_home_paths_repo_wide_rejects_tracked_offenders(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init_repo_with_tracked_doc(
        tmp_path,
        "docs/ref.md",
        "/Users/Morriz/.teleclaude/docs/general/spec/tools/telec-cli.md\n",
    )

    result = home_paths.main(["--project-root", str(tmp_path), "--repo-wide"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out
    assert captured.err


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_home_paths_repo_wide_allows_smudged_tilde_resource_refs(tmp_path: Path) -> None:
    _init_repo_with_tracked_doc(
        tmp_path,
        "docs/ref.md",
        "@~/.teleclaude/docs/general/spec/tools/telec-cli.md\n",
    )

    result = home_paths.main(["--project-root", str(tmp_path), "--repo-wide"])

    assert result == 0


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_home_paths_repo_wide_allows_clean_tracked_tree(tmp_path: Path) -> None:
    _init_repo_with_tracked_doc(
        tmp_path,
        "docs/ref.md",
        "Use a relative project documentation link.\n",
    )

    result = home_paths.main(["--project-root", str(tmp_path), "--repo-wide"])

    assert result == 0


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_home_paths_repo_wide_surfaces_git_errors(tmp_path_factory: pytest.TempPathFactory) -> None:
    not_a_git_repo = tmp_path_factory.mktemp("not-a-git-repo")
    with pytest.raises(RuntimeError):
        home_paths.main(["--project-root", str(not_a_git_repo), "--repo-wide"])
