"""Demo validation logic extracted for direct import by daemon code.

Avoids subprocess calls to `telec todo demo validate` from the daemon.
The CLI (`telec.py`) keeps its own inline copy for now — this module is
the canonical service-layer entry point for non-CLI callers.
"""

from __future__ import annotations

import re
from pathlib import Path


def _find_demo_md(slug: str, project_root: Path) -> Path | None:
    """Find demo.md for a slug. Searches todos/ first, then demos/."""
    for candidate in [
        project_root / "todos" / slug / "demo.md",
        project_root / "demos" / slug / "demo.md",
    ]:
        if candidate.exists():
            return candidate
    return None


def _check_no_demo_marker(content: str) -> str | None:
    """Check for <!-- no-demo: reason --> marker in first 10 lines."""
    pattern = re.compile(r"<!--\s*no-demo:\s*(.+?)\s*-->")
    for line in content.split("\n")[:10]:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def _extract_demo_blocks(content: str) -> list[tuple[int, str, bool, str]]:
    """Extract bash blocks from demo.md with skip-validation metadata.

    Returns tuples of (line_number, block_text, skipped, skip_reason).
    """
    blocks: list[tuple[int, str, bool, str]] = []
    skip_pattern = re.compile(r"<!--\s*skip-validation:\s*(.+?)\s*-->")
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        skip_match = skip_pattern.search(line)
        if skip_match:
            skip_reason = skip_match.group(1)
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("```bash"):
                block_start = j + 1
                block_lines: list[str] = []
                k = block_start
                while k < len(lines) and lines[k].strip() != "```":
                    block_lines.append(lines[k])
                    k += 1
                blocks.append((j + 1, "\n".join(block_lines), True, skip_reason))
                i = k + 1
                continue
            i += 1
            continue

        if line.strip().startswith("```bash"):
            block_start = i + 1
            block_lines = []
            k = block_start
            while k < len(lines) and lines[k].strip() != "```":
                block_lines.append(lines[k])
                k += 1
            blocks.append((i + 1, "\n".join(block_lines), False, ""))
            i = k + 1
            continue

        i += 1

    return blocks


def validate_demo(slug: str, project_root: Path) -> tuple[bool, bool, str]:
    """Validate demo.md structure for a slug.

    Returns (passed, is_no_demo, message).
    """
    demo_md_path = _find_demo_md(slug, project_root)
    if demo_md_path is None:
        return False, False, f"No demo.md found for '{slug}'"

    content = demo_md_path.read_text(encoding="utf-8")

    no_demo_reason = _check_no_demo_marker(content)
    if no_demo_reason is not None:
        msg = (
            f"WARNING: no-demo marker found: {no_demo_reason}\n"
            "Reviewer must verify justification — only pure internal refactors "
            "with zero user-visible change qualify."
        )
        return True, True, msg

    skeleton_path = project_root / "templates" / "todos" / "demo.md"
    if skeleton_path.exists():
        skeleton = skeleton_path.read_text(encoding="utf-8").replace("{slug}", slug)
        if content.strip() == skeleton.strip():
            return False, False, "demo.md is unchanged from the skeleton template — no demo implemented"

    blocks = _extract_demo_blocks(content)
    executable = [b for b in blocks if not b[2]]

    if not executable:
        return False, False, "No executable bash blocks found"

    lines = [f"Validation passed: {len(executable)} executable block(s) found"]
    if len(blocks) > len(executable):
        lines.append(f"Skipped: {len(blocks) - len(executable)} block(s)")
    return True, False, "\n".join(lines)
