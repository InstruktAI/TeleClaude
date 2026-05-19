from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from teleclaude.constants import SNIPPET_STATUS_TARGET
from teleclaude.resource_validation import _snippet


def _load_markdown_lint() -> ModuleType:
    script_path = Path(__file__).resolve().parents[4] / "tools" / "lint" / "markdown.py"
    spec = importlib.util.spec_from_file_location("markdown_lint", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_frontmatter_accepts_third_party_schema() -> None:
    markdown_lint = _load_markdown_lint()
    path = markdown_lint.REPO_ROOT / "docs" / "third-party" / "library" / "guide.md"

    errors = markdown_lint._validate_frontmatter(
        path,
        {
            "id": "third-party/library/guide",
            "type": "third-party",
            "scope": "project",
            "description": "Library guide",
        },
        domains={"software-development"},
    )

    assert errors == []


def test_main_runs_shared_snippet_validation_for_status_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown_lint = _load_markdown_lint()
    snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/snippet\n"
            "type: spec\n"
            "scope: project\n"
            "description: Snippet\n"
            f"status: {SNIPPET_STATUS_TARGET}\n"
            "---\n"
            "# Snippet\n\n"
            "## What it is\nBody.\n\n"
            "## Canonical fields\nBody.\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(markdown_lint, "REPO_ROOT", tmp_path)

    result = markdown_lint.main()

    assert result == 1
    assert _snippet.SNIPPET_STATUS_TARGET_MISSING_DELIVERED_BY in capsys.readouterr().err
