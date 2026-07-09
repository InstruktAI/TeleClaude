"""Functional coverage for downstream quality skeleton setup."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from teleclaude.project_setup import init_flow
from teleclaude.project_setup.skeleton import deploy_skeleton

_SPEC = "general/spec/tools/telec-cli"
_INSTALL_PYTHON_TOKEN = "INSTALL_PYTHON"
_PRECOMMIT_PATH = Path(".githooks") / "pre-commit"
_POSTMERGE_PATH = Path(".githooks") / "post-merge"


def _seed_python_project(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("print('ready')\n", encoding="utf-8")
    (project_root / "teleclaude.yml").write_text("project_name: Demo Project\n", encoding="utf-8")


def _seed_rust_project(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "Cargo.toml").write_text('[package]\nname = "demo"\n', encoding="utf-8")


def _git(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_python_quality_skeleton_creates_nested_hook_material(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)

    deploy_skeleton(project_root)

    hook_path = project_root / _PRECOMMIT_PATH
    postmerge_path = project_root / _POSTMERGE_PATH
    assert hook_path.is_file()
    assert postmerge_path.is_file()
    assert (hook_path.stat().st_mode & stat.S_IXUSR) == 0
    assert (postmerge_path.stat().st_mode & stat.S_IXUSR) == 0
    assert (project_root / "Makefile").is_file()
    assert not (project_root / "tools" / "quality.sh").exists()
    assert (project_root / "pyproject.toml").is_file()
    assert (project_root / ".pre-commit-config.yaml").is_file()
    assert {
        "contains_install_python": _INSTALL_PYTHON_TOKEN in hook_path.read_text(encoding="utf-8"),
        "created_parent": hook_path.parent.is_dir(),
        "hook_path": hook_path.relative_to(project_root).as_posix(),
        "post_merge_hook_path": postmerge_path.relative_to(project_root).as_posix(),
    } == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_projects_init_installs_thin_precommit_hook_without_legacy_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)

    monkeypatch.setattr(init_flow, "sync_project_artifacts", lambda _project_root: None)
    monkeypatch.setattr(init_flow, "register_root", lambda *, project_root: None)
    monkeypatch.setattr(init_flow, "seed_event_domains", lambda _project_root: None)

    init_flow.init_project(project_root)

    hook_destination = project_root / _git(project_root, "rev-parse", "--git-path", "hooks/pre-commit")
    postmerge_destination = project_root / _git(project_root, "rev-parse", "--git-path", "hooks/post-merge")
    hook_content = hook_destination.read_text(encoding="utf-8")
    postmerge_content = postmerge_destination.read_text(encoding="utf-8")
    assert hook_destination.is_file()
    assert postmerge_destination.is_file()
    assert hook_destination.stat().st_mode & stat.S_IXUSR
    assert postmerge_destination.stat().st_mode & stat.S_IXUSR
    assert {
        "contains_install_python": _INSTALL_PYTHON_TOKEN in hook_content,
        "destination": hook_destination.relative_to(project_root).as_posix(),
        "matches_project_hook": hook_content == (project_root / _PRECOMMIT_PATH).read_text(encoding="utf-8"),
        "post_merge_destination": postmerge_destination.relative_to(project_root).as_posix(),
        "post_merge_matches_project_hook": postmerge_content
        == (project_root / _POSTMERGE_PATH).read_text(encoding="utf-8"),
    } == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_generated_python_project_makefile_uses_explicit_project_owned_placeholders(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)
    deploy_skeleton(project_root)

    makefile = (project_root / "Makefile").read_text(encoding="utf-8")

    assert {"makefile": makefile} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_python_skeleton_merges_blessed_gitignore(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)

    deploy_skeleton(project_root)

    gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    assert {"gitignore": gitignore} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_gitignore_merge_preserves_project_entries_and_is_idempotent(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_python_project(project_root)
    (project_root / ".gitignore").write_text("# project-owned\nmy_secret_dir/\n", encoding="utf-8")

    deploy_skeleton(project_root)
    first = (project_root / ".gitignore").read_text(encoding="utf-8")
    deploy_skeleton(project_root)
    second = (project_root / ".gitignore").read_text(encoding="utf-8")

    assert first == second  # idempotent — the second merge appends nothing
    # The snapshot captures both the preserved project entry and the appended blessed set.
    assert {"merged_gitignore": first} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_gitignore_merge_dedupes_patterns_shared_across_languages(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("print('ready')\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (project_root / "tsconfig.json").write_text("{}\n", encoding="utf-8")

    # `dist/` ships in both the python and typescript blessed sets; the merge must
    # emit each pattern once. Enter through the real deployment surface and pin the
    # deduped cross-language output.
    deploy_skeleton(project_root)

    merged = (project_root / ".gitignore").read_text(encoding="utf-8")
    assert {"merged_gitignore": merged} == snapshot


@pytest.mark.functional
@pytest.mark.spec(_SPEC, "project-setup-quality-skeleton")
def test_generated_rust_project_receives_language_neutral_lifecycle_makefile(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "downstream"
    _seed_rust_project(project_root)
    deploy_skeleton(project_root)

    makefile = (project_root / "Makefile").read_text(encoding="utf-8")

    assert {"makefile": makefile} == snapshot
