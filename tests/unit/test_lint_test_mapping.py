"""Unit tests for test_mapping.py CI enforcement script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_test_mapping_module():
    path = Path(__file__).resolve().parents[2] / "tools" / "lint" / "test_mapping.py"
    spec = importlib.util.spec_from_file_location("lint_test_mapping", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pyproject(tmp_path: Path, exclude: list[str] | None = None) -> None:
    """Write a minimal pyproject.toml with [tool.test-mapping] config."""
    lines = ["[tool.test-mapping]"]
    if exclude is not None:
        items = ", ".join(f'"{e}"' for e in exclude)
        lines.append(f"exclude = [{items}]")
    (tmp_path / "pyproject.toml").write_text("\n".join(lines), encoding="utf-8")


def test_load_exclusions_reads_pyproject(tmp_path: Path) -> None:
    module = _load_test_mapping_module()
    _write_pyproject(tmp_path, exclude=["teleclaude/foo.py", "teleclaude/bar.py"])
    result: set[str] = module._load_exclusions(tmp_path)
    assert result == {"teleclaude/foo.py", "teleclaude/bar.py"}


def test_load_exclusions_empty_when_no_section(tmp_path: Path) -> None:
    module = _load_test_mapping_module()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    result: set[str] = module._load_exclusions(tmp_path)
    assert result == set()


def test_mirror_path_replaces_prefix_and_renames_file() -> None:
    module = _load_test_mapping_module()
    result: str = module._mirror_path("teleclaude/adapters/base_adapter.py")
    assert result == "tests/unit/adapters/test_base_adapter.py"


def test_mirror_path_nested_module() -> None:
    module = _load_test_mapping_module()
    result: str = module._mirror_path("teleclaude/cli/tui/views/sessions.py")
    assert result == "tests/unit/cli/tui/views/test_sessions.py"


def test_mirror_path_top_level_module() -> None:
    module = _load_test_mapping_module()
    result: str = module._mirror_path("teleclaude/utils.py")
    assert result == "tests/unit/test_utils.py"


def test_main_exits_nonzero_when_gaps_exist(tmp_path: Path) -> None:
    module = _load_test_mapping_module()
    (tmp_path / "teleclaude").mkdir()
    (tmp_path / "teleclaude" / "widgets.py").write_text("# source\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        module.main(repo_root=tmp_path)
    assert exc_info.value.code == 1


def test_main_exits_2_when_source_dir_missing(tmp_path: Path) -> None:
    module = _load_test_mapping_module()
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        module.main(repo_root=tmp_path)
    assert exc_info.value.code == 2


def test_main_exits_zero_when_all_mapped(tmp_path: Path) -> None:
    module = _load_test_mapping_module()
    (tmp_path / "teleclaude").mkdir()
    (tmp_path / "teleclaude" / "widgets.py").write_text("# source\n", encoding="utf-8")
    test_file = tmp_path / "tests" / "unit" / "test_widgets.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("# test\n", encoding="utf-8")
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        module.main(repo_root=tmp_path)
    assert exc_info.value.code == 0


def test_main_excludes_files_in_pyproject(tmp_path: Path) -> None:
    module = _load_test_mapping_module()
    (tmp_path / "teleclaude").mkdir()
    (tmp_path / "teleclaude" / "trivial.py").write_text("# no test needed\n", encoding="utf-8")
    _write_pyproject(tmp_path, exclude=["teleclaude/trivial.py"])

    with pytest.raises(SystemExit) as exc_info:
        module.main(repo_root=tmp_path)
    assert exc_info.value.code == 0
