from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


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
