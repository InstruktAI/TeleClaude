"""Functional tests for company-scoped doc selection with cross-company isolation.

Spec: docs/project/spec/domain/context.md (UC-CTX-7)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teleclaude.config.schema import AppConfig, GlobalConfig, ProjectConfig
from teleclaude.context_selector import build_context_output

pytestmark = pytest.mark.functional

_SPEC = "project/spec/domain/context"

_ACME_SLUG = "acme"
_OTHER_SLUG = "other-co"
_ACME_SNIPPET_ID = "company/policy/security"
_OTHER_SNIPPET_ID = "company/policy/data-handling"


def _write_company_index(companies_root: Path, slug: str, snippet_id: str) -> None:
    """Write a company docs index with one path-derived (scope: global) snippet."""
    docs_root = companies_root / slug / "docs"
    rel_path = f"{snippet_id.replace('company/', '', 1)}.md"
    (docs_root / "policy").mkdir(parents=True, exist_ok=True)
    (docs_root / rel_path).write_text("# Company policy\n", encoding="utf-8")
    index = {
        "project_root": str(docs_root),
        "snippets": [
            {
                "id": snippet_id,
                "description": f"{slug} security policy.",
                "type": "policy",
                "scope": "global",
                "domain": "company",
                "visibility": "public",
                "path": rel_path,
            }
        ],
    }
    (docs_root / "index.yaml").write_text(json.dumps(index, indent=2), encoding="utf-8")


def _app_config(company: str | None) -> AppConfig:
    return AppConfig(global_=GlobalConfig(), project=ProjectConfig(project_slug="web", company=company))


def _setup_companies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    companies_root = tmp_path / "companies"
    _write_company_index(companies_root, _ACME_SLUG, _ACME_SNIPPET_ID)
    _write_company_index(companies_root, _OTHER_SLUG, _OTHER_SNIPPET_ID)
    monkeypatch.setattr("teleclaude.context_selector.COMPANIES_ROOT", companies_root)
    monkeypatch.setattr("teleclaude.context_selector.GLOBAL_DOCS_DIR", tmp_path / "ghome" / "docs")
    return tmp_path / "proj"


@pytest.mark.spec(_SPEC, "UC-CTX-7")
def test_member_project_sees_its_company_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project declaring a company sees that company's snippet tree."""
    project_root = _setup_companies(tmp_path, monkeypatch)

    output = build_context_output(
        areas=[], project_root=project_root, config=_app_config(_ACME_SLUG), effective_human_role="admin"
    )

    assert _ACME_SNIPPET_ID in output


@pytest.mark.spec(_SPEC, "UC-CTX-7")
def test_other_company_project_excludes_acme_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cross-company isolation: a project in another company sees none of acme's snippets."""
    project_root = _setup_companies(tmp_path, monkeypatch)

    output = build_context_output(
        areas=[], project_root=project_root, config=_app_config(_OTHER_SLUG), effective_human_role="admin"
    )

    # The negative assertion is the confidentiality contract: acme's tree is never
    # read for an other-company project, so its snippet is absent entirely while the
    # project's own company snippet is present.
    assert _OTHER_SNIPPET_ID in output
    assert _ACME_SNIPPET_ID not in output
    assert str(tmp_path / "companies" / _ACME_SLUG) not in output


@pytest.mark.spec(_SPEC, "UC-CTX-7")
def test_no_company_project_sees_no_company_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project that declares no company sees no company snippets at all."""
    project_root = _setup_companies(tmp_path, monkeypatch)

    output = build_context_output(
        areas=[], project_root=project_root, config=_app_config(None), effective_human_role="admin"
    )

    assert str(tmp_path / "companies") not in output
