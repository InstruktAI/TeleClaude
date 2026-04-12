"""Tests for the project catalog service."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from teleclaude.services.project_catalog import (
    ProjectCatalogService,
    ProjectNode,
)

pytestmark = pytest.mark.unit


def _write_project(
    root: Path,
    *,
    slug: str | None,
    name: str,
    job_slug: str | None = None,
) -> None:
    """Write a minimal ``teleclaude.yml`` for ``root``.

    When ``job_slug`` is provided, the project subscribes to that job under
    ``jobs:`` with a fixed valid ``JobScheduleConfig`` payload. This avoids
    loosely typed fixture dicts in the test.
    """
    root.mkdir(parents=True, exist_ok=True)
    lines = [f"project_name: {name}"]
    if slug is not None:
        lines.append(f"project_slug: {slug}")
    if job_slug is not None:
        lines.append("jobs:")
        lines.append(f"  {job_slug}:")
        lines.append("    category: system")
        lines.append("    when:")
        lines.append("      every: 5m")
    (root / "teleclaude.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(manifest_path: Path, roots: list[Path]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump({"projects": [str(r) for r in roots]}),
        encoding="utf-8",
    )


def test_list_projects_returns_nodes_with_slug_and_config(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    _write_project(alpha, slug="alpha", name="Alpha")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [alpha])

    svc = ProjectCatalogService(manifest_path=manifest)
    projects = svc.list_projects()

    assert len(projects) == 1
    node = projects[0]
    assert isinstance(node, ProjectNode)
    assert node.slug == "alpha"
    assert node.name == "Alpha"
    assert node.root == alpha.resolve()
    assert node.config.project_name == "Alpha"


def test_list_projects_derives_slug_when_config_omits_it(tmp_path: Path) -> None:
    beta = tmp_path / "Beta Project"
    _write_project(beta, slug=None, name="Beta Project")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [beta])

    svc = ProjectCatalogService(manifest_path=manifest)
    node = svc.list_projects()[0]

    assert node.slug == "beta-project"


def test_list_projects_skips_roots_missing_teleclaude_yml(tmp_path: Path) -> None:
    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / "teleclaude.yml").write_text(yaml.safe_dump({"project_name": "Ok"}), encoding="utf-8")
    broken = tmp_path / "broken"
    broken.mkdir()
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [ok, broken])

    svc = ProjectCatalogService(manifest_path=manifest)
    slugs = [node.slug for node in svc.list_projects()]

    assert slugs == ["ok"]


def test_list_projects_is_lazy_and_cached(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    _write_project(alpha, slug="alpha", name="Alpha")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [alpha])

    svc = ProjectCatalogService(manifest_path=manifest)
    first = svc.list_projects()
    # Mutate the manifest on disk; cached result must not change.
    _write_manifest(manifest, [])
    second = svc.list_projects()

    assert first == second
    assert len(second) == 1


def test_refresh_picks_up_manifest_changes(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write_project(alpha, slug="alpha", name="Alpha")
    _write_project(beta, slug="beta", name="Beta")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [alpha])

    svc = ProjectCatalogService(manifest_path=manifest)
    assert [n.slug for n in svc.list_projects()] == ["alpha"]

    _write_manifest(manifest, [alpha, beta])
    svc.refresh()

    assert sorted(n.slug for n in svc.list_projects()) == ["alpha", "beta"]


def test_get_by_slug_and_get_by_root(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    _write_project(alpha, slug="alpha", name="Alpha")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [alpha])

    svc = ProjectCatalogService(manifest_path=manifest)

    by_slug = svc.get_by_slug("alpha")
    by_root = svc.get_by_root(alpha)
    assert by_slug is not None and by_slug.slug == "alpha"
    assert by_root is not None and by_root.root == alpha.resolve()
    assert svc.get_by_slug("missing") is None
    assert svc.get_by_root(tmp_path / "missing") is None


def test_docs_index_path_derives_from_project_root(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    _write_project(alpha, slug="alpha", name="Alpha")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [alpha])

    node = ProjectCatalogService(manifest_path=manifest).list_projects()[0]

    assert node.docs_index_path == alpha.resolve() / "docs" / "project" / "index.yaml"


def test_iter_projects_with_job_filters_by_config_jobs(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write_project(alpha, slug="alpha", name="Alpha", job_slug="log_bug_hunter")
    _write_project(beta, slug="beta", name="Beta")
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, [alpha, beta])

    svc = ProjectCatalogService(manifest_path=manifest)
    subscribers = list(svc.iter_projects_with_job("log_bug_hunter"))

    assert [node.slug for node in subscribers] == ["alpha"]
