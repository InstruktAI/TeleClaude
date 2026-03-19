"""Leaf file/path checks shared across next-machine modules."""

from __future__ import annotations

import re
from pathlib import Path


FROM_MAIN_MARKER = "<!-- from-main:"


def check_file_exists(cwd: str, relative_path: str) -> bool:
    """Check if a file exists relative to cwd."""
    return (Path(cwd) / relative_path).exists()


def check_file_has_content(cwd: str, relative_path: str) -> bool:
    """Check if a file exists and contains real (non-scaffold) content."""
    fpath = Path(cwd) / relative_path
    if not fpath.exists():
        return False
    try:
        content = fpath.read_text(encoding="utf-8")
    except OSError:
        return False
    return _has_from_main_marker(content) or not _is_scaffold_template(content)


def _has_from_main_marker(content: str) -> bool:
    """Check if content starts with a from-main HTML comment marker."""
    return content.lstrip().startswith(FROM_MAIN_MARKER)


def _is_scaffold_template(content: str) -> bool:
    """Check if a todo artifact is still an unfilled scaffold template."""
    stripped = content.strip()
    if len(stripped) < 50:
        return True

    scaffold_phrases = (
        "Define the intended outcome",
        "Summarize the approach",
        "Complete this task",
        "Add or update tests",
        "Run `make test`",
        "Run `make lint`",
        "Verify no unchecked",
        "Confirm requirements are reflected",
        "Confirm implementation tasks",
        "Document any deferrals",
        "In scope",
        "Out of scope",
    )

    remaining_lines: list[str] = []
    for line in stripped.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or re.fullmatch(r"-{3,}", text):
            continue
        if re.fullmatch(r"-\s*(\[[ x]?\]\s*)?", text):
            continue
        if re.fullmatch(r"\*\*[^*]+\*\*\s*``", text):
            continue
        bare = re.sub(r"^-\s*", "", text)
        if any(phrase in bare for phrase in scaffold_phrases):
            continue
        remaining_lines.append(text)

    remaining = " ".join(remaining_lines).strip()
    return len(remaining) < 30
