import importlib.util
import sys
from pathlib import Path


def _load_distribute_module(tmp_path: Path):
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "distribute.py"
    spec = importlib.util.spec_from_file_location("distribute", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["distribute"] = module
    spec.loader.exec_module(module)
    return module


def test_expand_inline_refs_inlines_docs(tmp_path: Path) -> None:
    project_root = tmp_path
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    referenced = docs_dir / "example.md"
    referenced.write_text("---\ndescription: test\n---\n\nHello world\n", encoding="utf-8")

    content = "Required reads\n@docs/example.md\n"
    distribute = _load_distribute_module(tmp_path)
    source_file = docs_dir / "source.md"
    source_file.write_text(content, encoding="utf-8")
    expanded = distribute.expand_inline_refs(content, project_root=project_root, current_path=source_file)
    assert "Hello world" in expanded
