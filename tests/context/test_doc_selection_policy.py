"""Functional tests for the Selection policy scope and project content filters.

Spec: docs/project/spec/feature/context/doc-selection-policy.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import pytest

from teleclaude.context_selector import build_context_output
from teleclaude.services.project_catalog import service as catalog_service
from teleclaude.services.project_catalog.service import ProjectCatalogService
from teleclaude.snippet_validation import SnippetScope

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/context/doc-selection-policy"

_GLOBAL_ID = "general/principle/example"
_PROJECT_ID = "project/spec/feature/context/proj-thing"
_FOREIGN_ID = "foreignproj/policy/foreign-thing"


class _IndexEntry(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    domain: str
    visibility: str
    path: str


def _write_index(index_path: Path, project_root: Path, entries: list[_IndexEntry]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps({"project_root": str(project_root), "snippets": entries}, indent=2),
        encoding="utf-8",
    )


def _entry(snippet_id: str, snippet_type: str, scope: str, domain: str, path: str) -> _IndexEntry:
    return {
        "id": snippet_id,
        "description": f"{snippet_id} snippet.",
        "type": snippet_type,
        "scope": scope,
        "domain": domain,
        "visibility": "public",
        "path": path,
    }


def _setup_global_and_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Wire a controlled global tree (one global snippet) plus a project tree.

    Returns the project root. The global snippet is reachable via the patched
    GLOBAL_SNIPPETS_DIR so the include factory keeps it; the project snippet is
    under the project's docs tree.
    """
    gdocs = tmp_path / "ghome" / ".teleclaude" / "docs"
    _write_index(
        gdocs / "index.yaml",
        gdocs,
        [_entry(_GLOBAL_ID, "principle", "global", "general", "general/principle/example.md")],
    )
    monkeypatch.setattr("teleclaude.context_selector.GLOBAL_SNIPPETS_DIR", gdocs)

    project_root = tmp_path / "proj"
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [_entry(_PROJECT_ID, "spec", "project", "project", "docs/project/spec/feature/context/proj-thing.md")],
    )
    return project_root


def test_no_filter_returns_global_and_project_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The unchanged default path lists both global and current-project snippets."""
    project_root = _setup_global_and_project(tmp_path, monkeypatch)

    output = build_context_output(areas=[], project_root=project_root)

    assert _GLOBAL_ID in output
    assert _PROJECT_ID in output


def test_global_snippet_in_unsubscribed_domain_is_included(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No subscriber gate: a global snippet in a domain the project does not list
    under business.domains is still surfaced (universal awareness)."""
    gdocs = tmp_path / "ghome" / ".teleclaude" / "docs"
    foreign_domain_id = "erp/policy/operating-disciplines"
    _write_index(
        gdocs / "index.yaml",
        gdocs,
        [_entry(foreign_domain_id, "policy", "global", "erp", "erp/policy/operating-disciplines.md")],
    )
    monkeypatch.setattr("teleclaude.context_selector.GLOBAL_SNIPPETS_DIR", gdocs)
    project_root = tmp_path / "proj"
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    (project_root / "teleclaude.yml").write_text(
        "project_slug: proj\nbusiness:\n  domains:\n    software-development: docs\n",
        encoding="utf-8",
    )

    output = build_context_output(areas=[], project_root=project_root)

    assert foreign_domain_id in output


@pytest.mark.spec(_SPEC, "UC-DSP1")
def test_scope_global_excludes_project_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--scope global returns only global snippets; project-scoped ones are excluded."""
    project_root = _setup_global_and_project(tmp_path, monkeypatch)

    output = build_context_output(areas=[], project_root=project_root, scope=SnippetScope.GLOBAL)

    assert _GLOBAL_ID in output
    assert _PROJECT_ID not in output


@pytest.mark.spec(_SPEC, "UC-DSP2")
def test_scope_project_excludes_global_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--scope project returns only project snippets; global ones are excluded."""
    project_root = _setup_global_and_project(tmp_path, monkeypatch)

    output = build_context_output(areas=[], project_root=project_root, scope=SnippetScope.PROJECT)

    assert _PROJECT_ID in output
    assert _GLOBAL_ID not in output


def test_scope_composes_with_areas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--scope intersects with --areas: a non-matching area drops the snippet even within scope."""
    project_root = _setup_global_and_project(tmp_path, monkeypatch)

    # The lone global snippet is a principle; filtering areas=policy yields nothing.
    output = build_context_output(areas=["policy"], project_root=project_root, scope=SnippetScope.GLOBAL)

    assert _GLOBAL_ID not in output
    # principle area keeps it.
    kept = build_context_output(areas=["principle"], project_root=project_root, scope=SnippetScope.GLOBAL)
    assert _GLOBAL_ID in kept


def _setup_foreign_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Register a foreign project in the catalog and return the current project root."""
    foreign_root = tmp_path / "foreign"
    (foreign_root / "docs").mkdir(parents=True, exist_ok=True)
    (foreign_root / "teleclaude.yml").write_text(
        "project_slug: foreignproj\nbusiness:\n  domains:\n    software-development: docs\n",
        encoding="utf-8",
    )
    _write_index(
        foreign_root / "docs" / "project" / "index.yaml",
        foreign_root,
        [
            _entry(
                "project/policy/foreign-thing", "policy", "project", "project", "docs/project/policy/foreign-thing.md"
            )
        ],
    )

    manifest = tmp_path / "projects.yaml"
    manifest.write_text(json.dumps({"projects": [str(foreign_root)]}), encoding="utf-8")
    # setitem auto-reverts the singleton slot after the test, so the catalog does
    # not leak into sibling tests.
    monkeypatch.setitem(catalog_service._INSTANCE_SLOT, "default", ProjectCatalogService(manifest_path=manifest))

    project_root = _setup_global_and_project(tmp_path, monkeypatch)
    return project_root


@pytest.mark.spec(_SPEC, "UC-DSP3")
def test_project_filter_returns_only_that_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--project <slug> returns only that project's snippets (global + current excluded), composing with --scope/--areas."""
    project_root = _setup_foreign_catalog(tmp_path, monkeypatch)

    output = build_context_output(areas=[], project_root=project_root, projects=["foreignproj"])
    assert _FOREIGN_ID in output
    assert _GLOBAL_ID not in output
    assert _PROJECT_ID not in output

    # Composes with --scope: the foreign snippet is project-scoped, so --scope global removes it.
    removed = build_context_output(
        areas=[], project_root=project_root, projects=["foreignproj"], scope=SnippetScope.GLOBAL
    )
    assert _FOREIGN_ID not in removed

    # Composes with --areas: the foreign snippet is a policy — areas=policy keeps it, areas=spec drops it.
    kept = build_context_output(areas=["policy"], project_root=project_root, projects=["foreignproj"])
    assert _FOREIGN_ID in kept
    dropped = build_context_output(areas=["spec"], project_root=project_root, projects=["foreignproj"])
    assert _FOREIGN_ID not in dropped


@pytest.mark.spec(_SPEC, "UC-DSP4")
def test_unknown_project_slug_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--project <unknown> yields an empty result, not an error."""
    project_root = _setup_foreign_catalog(tmp_path, monkeypatch)

    output = build_context_output(areas=[], project_root=project_root, projects=["does-not-exist"])

    assert _FOREIGN_ID not in output
    assert _GLOBAL_ID not in output
    assert _PROJECT_ID not in output


_GLOBAL_TP_ID = "third-party/global-lib"
_PROJECT_TP_ID = "third-party/project-lib"


def _write_third_party_index(index_path: Path, entries: list[dict[str, str]]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps({"snippets_root": str(index_path.parent), "snippets": entries}, indent=2),
        encoding="utf-8",
    )


def _setup_third_party(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Wire global + project third-party indexes alongside the taxonomy fixtures."""
    project_root = _setup_global_and_project(tmp_path, monkeypatch)

    repo_root = tmp_path / "repo"
    _write_third_party_index(
        repo_root / "docs" / "third-party" / "index.yaml",
        [{"id": _GLOBAL_TP_ID, "description": "Global lib.", "scope": "global", "path": "global-lib.md"}],
    )
    monkeypatch.setattr("teleclaude.context_selector.REPO_ROOT", repo_root)

    _write_third_party_index(
        project_root / "docs" / "third-party" / "index.yaml",
        [{"id": _PROJECT_TP_ID, "description": "Project lib.", "scope": "project", "path": "project-lib.md"}],
    )
    return project_root


def test_scope_filters_third_party_by_entry_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--third-party composes with --scope: only entries of the requested scope survive."""
    project_root = _setup_third_party(tmp_path, monkeypatch)

    both = build_context_output(areas=[], project_root=project_root, include_third_party=True)
    assert _GLOBAL_TP_ID in both
    assert _PROJECT_TP_ID in both

    only_global = build_context_output(
        areas=[], project_root=project_root, include_third_party=True, scope=SnippetScope.GLOBAL
    )
    assert _GLOBAL_TP_ID in only_global
    assert _PROJECT_TP_ID not in only_global

    only_project = build_context_output(
        areas=[], project_root=project_root, include_third_party=True, scope=SnippetScope.PROJECT
    )
    assert _PROJECT_TP_ID in only_project
    assert _GLOBAL_TP_ID not in only_project


def test_project_filter_drops_third_party(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--third-party composes with --project: third-party entries are dropped entirely."""
    project_root = _setup_foreign_catalog(tmp_path, monkeypatch)
    repo_root = tmp_path / "repo"
    _write_third_party_index(
        repo_root / "docs" / "third-party" / "index.yaml",
        [{"id": _GLOBAL_TP_ID, "description": "Global lib.", "scope": "global", "path": "global-lib.md"}],
    )
    monkeypatch.setattr("teleclaude.context_selector.REPO_ROOT", repo_root)

    output = build_context_output(
        areas=[], project_root=project_root, projects=["foreignproj"], include_third_party=True
    )

    assert _GLOBAL_TP_ID not in output
