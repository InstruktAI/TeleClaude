"""Test that distribute.py processes .agents/ commands for non-mother projects."""

import importlib.util
import os
import sys
from pathlib import Path

from frontmatter import Post


def _load_distribute_module() -> object:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "distribute.py"
    spec = importlib.util.spec_from_file_location("distribute", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["distribute"] = module
    spec.loader.exec_module(module)
    return module


def test_local_agents_generates_codex_commands(tmp_path: Path) -> None:
    """distribute.py should transpile .agents/commands/ into codex prompts."""
    project_root = tmp_path
    (project_root / "AGENTS.md").write_text("# AGENTS.md\n", encoding="utf-8")

    # distribute.py needs .agents/commands/ with valid command content
    commands_dir = project_root / ".agents" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "test-cmd.md").write_text(
        "---\ndescription: A test command\n---\n\n"
        "# Test Command\n\nYou are now the test runner.\n\n"
        "## Purpose\n\nRun tests.\n\n"
        "## Inputs\n\nNone.\n\n"
        "## Outputs\n\nNone.\n\n"
        "## Steps\n\n1. Do something\n",
        encoding="utf-8",
    )

    home_dir = tmp_path / "home"
    (home_dir / ".codex").mkdir(parents=True)

    distribute = _load_distribute_module()
    distribute._format_markdown = lambda _: None
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

    # Codex prompts should be transpiled into dist/local/codex/prompts/
    codex_prompts = project_root / "dist" / "local" / "codex" / "prompts"
    assert codex_prompts.exists(), "Codex prompts directory should be created"
    prompt_files = list(codex_prompts.glob("*.md"))
    assert len(prompt_files) > 0, "At least one codex prompt should be generated"


def test_transform_to_codex_quotes_scalar_frontmatter(tmp_path: Path) -> None:
    """Codex transform should single-quote scalar frontmatter values."""
    distribute = _load_distribute_module()
    post = Post("Body", description="Value: with colon", name="demo")

    rendered = distribute.transform_to_codex(post)

    assert rendered.startswith("---\n")
    assert "description: 'Value: with colon'" in rendered
    assert "name: 'demo'" in rendered


def test_transform_skill_to_codex_preserves_nested_metadata(tmp_path: Path) -> None:
    """Codex skill transform should quote scalars while keeping nested mappings."""
    distribute = _load_distribute_module()
    post = Post("Body", description="desc", hooks={"post": ["echo hi"]})

    rendered = distribute.transform_skill_to_codex(post, "youtube")

    assert "name: 'youtube'" in rendered
    assert "description: 'desc'" in rendered
    assert "\nhooks:\n" in rendered


def test_transform_to_codex_rewrites_next_commands_to_prompts() -> None:
    """Codex transform should rewrite /next-* command tokens for prompt execution."""
    distribute = _load_distribute_module()
    post = Post("Run `/next-prepare-draft my-slug` then `/next-prepare-gate my-slug`.", description="desc")

    rendered = distribute.transform_to_codex(post)

    assert "/prompts:next-prepare-draft my-slug" in rendered
    assert "/prompts:next-prepare-gate my-slug" in rendered
    assert "/next-prepare-draft my-slug" not in rendered


def test_transform_to_codex_does_not_rewrite_path_like_next_refs() -> None:
    """Codex transform should not rewrite filesystem path fragments containing /next-*."""
    distribute = _load_distribute_module()
    post = Post("Read @/Users/me/docs/next-prepare.md before review.", description="desc")

    rendered = distribute.transform_to_codex(post)

    assert "@/Users/me/docs/next-prepare.md" in rendered
    assert "/prompts:next-prepare.md" not in rendered
