from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import frontmatter

# guard: no-companion


def _load_script() -> ModuleType:
    script_path = Path(__file__).resolve().parents[3] / "tools" / "docs" / "update_third_party_frontmatter.py"
    spec = importlib.util.spec_from_file_location("update_third_party_frontmatter", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_update_tree_adds_required_frontmatter_without_changing_body(tmp_path: Path) -> None:
    updater = _load_script()
    third_party_root = tmp_path / "docs" / "third-party"
    doc_path = third_party_root / "library" / "guide.md"
    doc_path.parent.mkdir(parents=True)
    body = "# Library Guide\n\n## Sources\n- https://example.com\n"
    doc_path.write_text(body, encoding="utf-8")

    results = updater.update_tree(third_party_root, scope="project")

    assert [result.path for result in results if result.changed] == [doc_path]
    post = frontmatter.loads(doc_path.read_text(encoding="utf-8"))
    assert post.metadata == {
        "id": "third-party/library/guide",
        "type": "third-party",
        "scope": "project",
        "description": "Library Guide",
    }
    assert post.content == body.rstrip("\n")
