"""Functional tests for derived doc snippet index shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.docs_index import build_index_payload
from teleclaude.slug import normalize_slug

pytestmark = pytest.mark.functional


def _write_snippet(path: Path, *, description: str, title: str = "Example") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
description: {description}
---
# {title}

## What

Fixture body.

## Why

Fixture reason.
""",
        encoding="utf-8",
    )
    return path


def test_index_derives_classifier_fields_from_stripped_frontmatter(tmp_path: Path, snapshot: object) -> None:
    snippet = _write_snippet(
        tmp_path / "docs" / "project" / "concept" / "derived-entry.md",
        description="Derived entry.",
    )

    payload = build_index_payload(tmp_path, tmp_path / "docs" / "project")

    assert len(payload["snippets"]) == 1
    entry = dict(payload["snippets"][0])
    assert entry.pop("source_project") == normalize_slug(tmp_path.name)
    assert entry.pop("path") == str(snippet.relative_to(tmp_path))
    assert entry == snapshot


def test_global_index_includes_baseline_and_activation_trigger_shape(tmp_path: Path, snapshot: object) -> None:
    _write_snippet(
        tmp_path / "docs" / "global" / "general" / "procedure" / "doc-authoring.md",
        description="Doc authoring.",
        title="Doc Authoring",
    )
    baseline = tmp_path / "docs" / "global" / "baseline" / "principle" / "grounding.md"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text("# Grounding\n\nBaseline fixture.\n", encoding="utf-8")

    payload = build_index_payload(tmp_path, tmp_path / "docs" / "global")

    entries = {entry["id"]: entry for entry in payload["snippets"]}
    assert {
        "general": {
            "activation_trigger": entries["general/procedure/doc-authoring"]["activation_trigger"],
            "domain": entries["general/procedure/doc-authoring"]["domain"],
        },
        "baseline": {
            "activation_trigger": entries["baseline/principle/grounding"]["activation_trigger"],
            "domain": entries["baseline/principle/grounding"]["domain"],
        },
    } == snapshot


def test_index_build_fails_loudly_for_non_derivable_snippet_path(tmp_path: Path) -> None:
    _write_snippet(
        tmp_path / "docs" / "project" / "unknown" / "bad.md",
        description="Bad path.",
    )

    with pytest.raises(ValueError, match="Cannot derive snippet classification"):
        build_index_payload(tmp_path, tmp_path / "docs" / "project")
