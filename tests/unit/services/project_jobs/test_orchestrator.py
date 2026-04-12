"""Tests for the generic project-job orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from teleclaude.services.project_catalog import ProjectCatalogService, ProjectNode
from teleclaude.services.project_jobs.orchestrator import ProjectJobOrchestrator

pytestmark = pytest.mark.unit


def _write_project(
    root: Path,
    *,
    slug: str,
    name: str,
    job_slugs: tuple[str, ...] = (),
) -> None:
    """Write a minimal ``teleclaude.yml`` for ``root``.

    ``job_slugs`` subscribes the project to each listed job under a fixed
    valid ``JobScheduleConfig`` payload. We emit YAML as text rather than
    dumping a loosely typed dict so the fixture stays within the typed-dict
    guardrails.
    """
    root.mkdir(parents=True, exist_ok=True)
    lines = [f"project_name: {name}", f"project_slug: {slug}"]
    if job_slugs:
        lines.append("jobs:")
        for job_slug in job_slugs:
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


def _build_catalog(tmp_path: Path, projects: list[tuple[str, tuple[str, ...]]]) -> ProjectCatalogService:
    roots: list[Path] = []
    for slug, job_slugs in projects:
        root = tmp_path / slug
        _write_project(root, slug=slug, name=slug.capitalize(), job_slugs=job_slugs)
        roots.append(root)
    manifest = tmp_path / "projects.yaml"
    _write_manifest(manifest, roots)
    return ProjectCatalogService(manifest_path=manifest)


@pytest.mark.asyncio
async def test_run_once_dispatches_only_subscribed_projects(tmp_path: Path) -> None:
    catalog = _build_catalog(
        tmp_path,
        [("alpha", ("log_bug_hunter",)), ("beta", ()), ("gamma", ("log_bug_hunter",))],
    )

    invoked: list[str] = []

    async def _run(node: ProjectNode) -> bool:
        invoked.append(node.slug)
        return True

    orch = ProjectJobOrchestrator(
        catalog=catalog,
        job_slug="log_bug_hunter",
        run_for_project=_run,
    )

    results = await orch.run_once()

    assert sorted(invoked) == ["alpha", "gamma"]
    assert sorted(slug for slug, _ in results) == ["alpha", "gamma"]
    assert all(dispatched for _, dispatched in results)


@pytest.mark.asyncio
async def test_run_once_isolates_failures_per_project(tmp_path: Path) -> None:
    catalog = _build_catalog(
        tmp_path,
        [("alpha", ("log_bug_hunter",)), ("beta", ("log_bug_hunter",))],
    )

    async def _run(node: ProjectNode) -> bool:
        if node.slug == "alpha":
            raise RuntimeError("alpha exploded")
        return True

    orch = ProjectJobOrchestrator(
        catalog=catalog,
        job_slug="log_bug_hunter",
        run_for_project=_run,
    )

    results = await orch.run_once()

    outcomes = dict(results)
    assert outcomes["alpha"] is False  # error isolated, not dispatched
    assert outcomes["beta"] is True


@pytest.mark.asyncio
async def test_run_once_returns_empty_list_when_no_subscribers(tmp_path: Path) -> None:
    catalog = _build_catalog(tmp_path, [("alpha", ()), ("beta", ())])

    async def _run(node: ProjectNode) -> bool:  # pragma: no cover - must not be called
        raise AssertionError(f"run_for_project should not be invoked: {node.slug}")

    orch = ProjectJobOrchestrator(
        catalog=catalog,
        job_slug="log_bug_hunter",
        run_for_project=_run,
    )

    assert await orch.run_once() == []
