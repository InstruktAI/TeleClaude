"""Functional tests for Blueprint generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.constants import ENV_ENABLE, INTEGRATOR_GITOP_ENV
from teleclaude.core.blueprint._paths import GRAPH_FILENAME, graph_path, manifest_path
from teleclaude.core.blueprint.generate import regenerate_blueprint
from teleclaude.core.blueprint.manifest import BlueprintStatus, read_manifest
from teleclaude.core.blueprint.post_merge import run_post_merge_regeneration
from teleclaude.git import GIT_EXECUTABLE

pytestmark = pytest.mark.functional


# guard: loose-dict-func - fixture mirroring the graph.json contract under test
def _larger_graph() -> dict[str, object]:
    return {
        "directed": True,
        "nodes": [
            {"id": "kept", "source_file": "kept.py", "label": "kept()"},
            {"id": "removed", "source_file": "removed.py", "label": "removed()"},
        ],
        "links": [],
    }


# guard: loose-dict-func - fixture mirroring the graph.json contract under test
def _smaller_graph() -> dict[str, object]:
    return {
        "directed": True,
        "nodes": [{"id": "kept", "source_file": "kept.py", "label": "kept()"}],
        "links": [],
    }


def test_regenerate_blueprint_overwrites_cache_when_extraction_has_fewer_nodes(tmp_path: Path) -> None:
    """A shrinking re-extraction succeeds and promotes the smaller graph to the Blueprint cache."""
    graph_path(tmp_path).parent.mkdir(parents=True)
    graph_path(tmp_path).write_text(json.dumps(_larger_graph()), encoding="utf-8")

    def fake_graphify_update(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        root = Path(args[2])
        source_graph = root / "graphify-out" / GRAPH_FILENAME
        source_graph.parent.mkdir(parents=True)
        source_graph.write_text(json.dumps(_smaller_graph()), encoding="utf-8")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0 if len(args) == 4 else 1,
            stdout="",
            stderr="node count decreased",
        )

    with patch("teleclaude.core.blueprint.generate.subprocess.run", side_effect=fake_graphify_update):
        manifest = regenerate_blueprint(tmp_path, baseline_sha="mainbaselinesha0001")

    assert manifest.status is BlueprintStatus.OK
    assert json.loads(graph_path(tmp_path).read_text(encoding="utf-8")) == _smaller_graph()


def _git(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT_EXECUTABLE, *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _seed_repo_with_orig_head(project_root: Path) -> str:
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test User")
    (project_root / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(project_root, "add", "tracked.txt")
    _git(project_root, "commit", "-m", "before")
    orig_head = _git(project_root, "rev-parse", "HEAD")
    (project_root / "tracked.txt").write_text("after\n", encoding="utf-8")
    _git(project_root, "add", "tracked.txt")
    _git(project_root, "commit", "-m", "after")
    head = _git(project_root, "rev-parse", "HEAD")
    _git(project_root, "update-ref", "ORIG_HEAD", orig_head)
    return head


def test_post_merge_entrypoint_regenerates_when_head_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hook entrypoint regenerates the Blueprint at the post-merge HEAD."""
    head = _seed_repo_with_orig_head(tmp_path)
    monkeypatch.setenv("GRAPHIFY_REPO_ROOT", str(tmp_path))

    def fake_graphify_update(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        root = Path(args[2])
        source_graph = root / "graphify-out" / GRAPH_FILENAME
        source_graph.parent.mkdir(parents=True)
        source_graph.write_text(json.dumps(_smaller_graph()), encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with patch("teleclaude.core.blueprint.generate.subprocess.run", side_effect=fake_graphify_update):
        assert run_post_merge_regeneration() == 0

    assert json.loads(graph_path(tmp_path).read_text(encoding="utf-8")) == _smaller_graph()
    manifest = read_manifest(manifest_path(tmp_path))
    assert manifest is not None
    assert manifest.status is BlueprintStatus.OK
    assert manifest.baseline_sha == head


def test_post_merge_entrypoint_noops_when_integrator_suppresses_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The integrator suppression signal prevents hook-side regeneration."""
    _seed_repo_with_orig_head(tmp_path)
    monkeypatch.setenv("GRAPHIFY_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv(INTEGRATOR_GITOP_ENV, ENV_ENABLE)

    assert run_post_merge_regeneration() == 0
    assert not graph_path(tmp_path).exists()
