"""Functional tests for publisher-derived valid domains."""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.domains as domains
from teleclaude.domains import valid_domains
from teleclaude.snippet_validation import SnippetScope, derive_snippet_classification, load_domains

pytestmark = pytest.mark.functional


def _publisher(root: Path, *, publishes: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    body = "project_name: {name}\nbusiness:\n  publishes:\n{items}\n".format(
        name=root.name,
        items="\n".join(f"    - slug: {domain}\n      trigger: Use when working in {domain}" for domain in publishes)
        or "    []",
    )
    (root / "teleclaude.yml").write_text(body, encoding="utf-8")
    return root


def test_valid_domains_is_the_union_of_publisher_declarations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alpha = _publisher(tmp_path / "alpha", publishes=["software-development", "creative"])
    beta = _publisher(tmp_path / "beta", publishes=["erp", "creative"])
    monkeypatch.setattr(domains, "load_roots", lambda: [alpha, beta])

    assert valid_domains() == {"software-development", "creative", "erp"}


def test_undeclared_domain_is_rejected_by_classification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = _publisher(tmp_path / "alpha", publishes=["erp"])
    monkeypatch.setattr(domains, "load_roots", lambda: [publisher])

    resolved = load_domains(publisher)
    assert resolved == {"erp"}

    erp_path = publisher / "docs" / "global" / "erp" / "policy" / "billing.md"
    classification, reason = derive_snippet_classification(erp_path, project_root=publisher, domains=resolved)
    assert classification is not None
    assert classification.scope == SnippetScope.GLOBAL
    assert reason is None

    marketing_path = publisher / "docs" / "global" / "marketing" / "policy" / "ads.md"
    classification, reason = derive_snippet_classification(marketing_path, project_root=publisher, domains=resolved)
    assert classification is None
    assert reason
