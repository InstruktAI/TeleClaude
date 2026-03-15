"""Characterization tests for teleclaude/cli/demo_validation.py."""

from __future__ import annotations

from pathlib import Path

from teleclaude.cli.demo_validation import (
    _check_no_demo_marker,
    _extract_demo_blocks,
    _find_demo_md,
    validate_demo,
)

# ---------------------------------------------------------------------------
# _check_no_demo_marker
# ---------------------------------------------------------------------------


def test_no_demo_marker_returns_reason_when_present() -> None:
    content = "<!-- no-demo: pure internal refactor -->\n# Demo\n"
    result = _check_no_demo_marker(content)
    assert result == "pure internal refactor"


def test_no_demo_marker_returns_none_when_absent() -> None:
    content = "# Demo\n\n```bash\necho hello\n```\n"
    result = _check_no_demo_marker(content)
    assert result is None


def test_no_demo_marker_only_checked_in_first_10_lines() -> None:
    lines = ["# line\n"] * 11 + ["<!-- no-demo: late -->\n"]
    content = "".join(lines)
    result = _check_no_demo_marker(content)
    assert result is None


def test_no_demo_marker_with_extra_whitespace_in_comment() -> None:
    content = "<!--  no-demo:   trimmed reason  -->\n"
    result = _check_no_demo_marker(content)
    assert result == "trimmed reason"


# ---------------------------------------------------------------------------
# _extract_demo_blocks
# ---------------------------------------------------------------------------


def test_extract_demo_blocks_returns_executable_block() -> None:
    content = "## Setup\n```bash\necho hello\n```\n"
    blocks = _extract_demo_blocks(content)
    assert len(blocks) == 1
    _line_no, text, skipped, reason = blocks[0]
    assert skipped is False
    assert reason == ""
    assert "echo hello" in text


def test_extract_demo_blocks_skip_validation_marks_block_skipped() -> None:
    content = "<!-- skip-validation: requires display -->\n```bash\necho skip\n```\n"
    blocks = _extract_demo_blocks(content)
    assert len(blocks) == 1
    _line_no, text, skipped, reason = blocks[0]
    assert skipped is True
    assert reason == "requires display"
    assert "echo skip" in text


def test_extract_demo_blocks_mixed_executable_and_skipped() -> None:
    content = "```bash\necho run\n```\n<!-- skip-validation: manual -->\n```bash\necho skip\n```\n"
    blocks = _extract_demo_blocks(content)
    assert len(blocks) == 2
    executable = [b for b in blocks if not b[2]]
    skipped = [b for b in blocks if b[2]]
    assert len(executable) == 1
    assert len(skipped) == 1


def test_extract_demo_blocks_empty_content_returns_empty() -> None:
    blocks = _extract_demo_blocks("")
    assert blocks == []


def test_extract_demo_blocks_non_bash_fence_ignored() -> None:
    content = "```python\nprint('hello')\n```\n"
    blocks = _extract_demo_blocks(content)
    assert blocks == []


# ---------------------------------------------------------------------------
# _find_demo_md
# ---------------------------------------------------------------------------


def test_find_demo_md_returns_todos_path_when_present(tmp_path: Path) -> None:
    slug = "my-slug"
    demo_path = tmp_path / "todos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    demo_path.write_text("# Demo\n")
    result = _find_demo_md(slug, tmp_path)
    assert result == demo_path


def test_find_demo_md_falls_back_to_demos_path(tmp_path: Path) -> None:
    slug = "my-slug"
    demo_path = tmp_path / "demos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    demo_path.write_text("# Demo\n")
    result = _find_demo_md(slug, tmp_path)
    assert result == demo_path


def test_find_demo_md_returns_none_when_absent(tmp_path: Path) -> None:
    result = _find_demo_md("missing-slug", tmp_path)
    assert result is None


def test_find_demo_md_prefers_todos_over_demos(tmp_path: Path) -> None:
    slug = "my-slug"
    todos_path = tmp_path / "todos" / slug / "demo.md"
    todos_path.parent.mkdir(parents=True)
    todos_path.write_text("# Todos Demo\n")
    demos_path = tmp_path / "demos" / slug / "demo.md"
    demos_path.parent.mkdir(parents=True)
    demos_path.write_text("# Demos Demo\n")
    result = _find_demo_md(slug, tmp_path)
    assert result == todos_path


# ---------------------------------------------------------------------------
# validate_demo
# ---------------------------------------------------------------------------


def test_validate_demo_returns_failure_when_no_demo_md(tmp_path: Path) -> None:
    passed, is_no_demo, _msg = validate_demo("missing", tmp_path)
    assert passed is False
    assert is_no_demo is False


def test_validate_demo_returns_true_for_no_demo_marker(tmp_path: Path) -> None:
    slug = "my-slug"
    demo_path = tmp_path / "todos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    demo_path.write_text("<!-- no-demo: internal refactor only -->\n# Demo\n")
    passed, is_no_demo, _msg = validate_demo(slug, tmp_path)
    assert passed is True
    assert is_no_demo is True


def test_validate_demo_fails_when_no_executable_blocks(tmp_path: Path) -> None:
    slug = "my-slug"
    demo_path = tmp_path / "todos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    demo_path.write_text("# Demo\n\nJust text, no code blocks.\n")
    passed, is_no_demo, _msg = validate_demo(slug, tmp_path)
    assert passed is False
    assert is_no_demo is False


def test_validate_demo_passes_with_executable_block(tmp_path: Path) -> None:
    slug = "my-slug"
    demo_path = tmp_path / "todos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    demo_path.write_text("# Demo\n\n```bash\necho hello\n```\n")
    passed, is_no_demo, _msg = validate_demo(slug, tmp_path)
    assert passed is True
    assert is_no_demo is False


def test_validate_demo_fails_when_all_blocks_skipped(tmp_path: Path) -> None:
    slug = "my-slug"
    demo_path = tmp_path / "todos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    content = "# Demo\n<!-- skip-validation: manual -->\n```bash\necho skip\n```\n"
    demo_path.write_text(content)
    passed, _is_no_demo, _msg = validate_demo(slug, tmp_path)
    assert passed is False


def test_validate_demo_fails_when_content_matches_skeleton(tmp_path: Path) -> None:
    slug = "my-slug"
    skeleton_dir = tmp_path / "templates" / "todos"
    skeleton_dir.mkdir(parents=True)
    skeleton_content = "# Demo for {slug}\n\n```bash\necho placeholder\n```\n"
    (skeleton_dir / "demo.md").write_text(skeleton_content)

    demo_path = tmp_path / "todos" / slug / "demo.md"
    demo_path.parent.mkdir(parents=True)
    demo_path.write_text(skeleton_content.replace("{slug}", slug))
    passed, _is_no_demo, _msg = validate_demo(slug, tmp_path)
    assert passed is False
