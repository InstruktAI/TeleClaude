import importlib.util
import os
import sys
from pathlib import Path


def _load_distribute_module() -> object:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "distribute.py"
    spec = importlib.util.spec_from_file_location("distribute", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_agents_generates_repo_codex(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "example.md").write_text(
        "---\ndescription: test\n---\n\nHello local docs\n",
        encoding="utf-8",
    )
    (project_root / "AGENTS.md").write_text(
        "# AGENTS.md\n\n@docs/example.md\n",
        encoding="utf-8",
    )

    home_dir = tmp_path / "home"
    (home_dir / ".codex").mkdir(parents=True)

    distribute = _load_distribute_module()
    distribute._format_markdown = lambda _: None  # avoid slow prettier during tests
    original_home = os.environ.get("HOME")
    original_cwd = os.getcwd()
    original_argv = sys.argv[:]

    try:
        os.environ["HOME"] = str(home_dir)
        sys.argv = ["distribute.py", "--project-root", str(project_root)]
        distribute.main()
    finally:
        if original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_home
        sys.argv = original_argv
        os.chdir(original_cwd)

    repo_override = project_root / "AGENTS.override.md"
    assert repo_override.exists()
    content = repo_override.read_text(encoding="utf-8")
    assert "Hello local docs" in content
