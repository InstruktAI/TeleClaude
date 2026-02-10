#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
# ]
# ///
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, Mapping

import yaml

_REQUIRED_READS_HEADER = re.compile(r"^##\s+Required reads\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_READ_LINE = re.compile(r"^\s*-\s*@(\S+)\s*$")


def _split_frontmatter(lines: list[str]) -> tuple[list[str], list[str]] | None:
    if not lines or lines[0].strip() != "---":
        return None
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None
    frontmatter = lines[1:end_idx]
    body = lines[end_idx + 1 :]
    return frontmatter, body


def _load_metadata(frontmatter_lines: list[str]) -> Mapping[str, object]:
    raw = "\n".join(frontmatter_lines)
    data = yaml.safe_load(raw) or {}
    return data if isinstance(data, dict) else {}


def _strip_requires_frontmatter(frontmatter_lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    skip = False
    for line in frontmatter_lines:
        if skip:
            if line.startswith(" ") or line.startswith("\t"):
                continue
            skip = False
        if line.lstrip().startswith("requires:"):
            skip = True
            continue
        cleaned.append(line)
    return cleaned


def _extract_existing_required_reads(lines: list[str], start: int, end: int) -> list[str]:
    existing: list[str] = []
    for line in lines[start:end]:
        match = _REQUIRED_READ_LINE.match(line)
        if match:
            existing.append(match.group(1))
    return existing


def _insert_required_reads_section(lines: list[str], insert_pos: int, requires: list[str]) -> list[str]:
    bullets = [f"- @{req.lstrip('@')}" for req in requires]
    section = ["## Required reads", *bullets]
    if insert_pos > 0 and lines[insert_pos - 1].strip():
        section.insert(0, "")
    if insert_pos < len(lines) and lines[insert_pos].strip():
        section.append("")
    return lines[:insert_pos] + section + lines[insert_pos:]


def _update_required_reads(lines: list[str], requires: list[str]) -> list[str]:
    if not requires:
        return lines

    header_idx = None
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line):
            header_idx = idx
            break

    if header_idx is None:
        title_idx = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
        insert_pos = (title_idx + 1) if title_idx is not None else 0
        return _insert_required_reads_section(lines, insert_pos, requires)

    section_start = header_idx + 1
    section_end = next(
        (i for i in range(section_start, len(lines)) if _HEADER_LINE.match(lines[i])),
        len(lines),
    )
    existing = _extract_existing_required_reads(lines, section_start, section_end)
    missing = [req for req in requires if req not in existing]
    if not missing:
        return lines

    insert_pos = section_end
    while insert_pos > section_start and not lines[insert_pos - 1].strip():
        insert_pos -= 1
    new_lines = lines[:insert_pos] + [f"- @{req.lstrip('@')}" for req in missing] + lines[insert_pos:]
    return new_lines


def migrate_text(text: str) -> str:
    lines = text.splitlines()
    split = _split_frontmatter(lines)
    if split is None:
        return text

    frontmatter_lines, body_lines = split
    metadata = _load_metadata(frontmatter_lines)
    requires_raw = metadata.get("requires", [])
    requires = [req for req in requires_raw if isinstance(req, str)] if isinstance(requires_raw, list) else []
    if not requires and "requires" not in metadata:
        return text

    body_lines = _update_required_reads(body_lines, requires)
    cleaned_frontmatter = _strip_requires_frontmatter(frontmatter_lines)
    rebuilt = ["---", *cleaned_frontmatter, "---", *body_lines]
    rebuilt_text = "\n".join(rebuilt)
    if text.endswith("\n"):
        rebuilt_text += "\n"
    return rebuilt_text


def migrate_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = migrate_text(original)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _iter_markdown_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(root.rglob("*.md"))
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate frontmatter requires to Required reads sections and remove requires."
    )
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    roots = [project_root / "docs", project_root / "agents" / "docs"]
    changed: list[Path] = []
    for path in _iter_markdown_files(roots):
        if migrate_file(path):
            changed.append(path)

    if changed:
        print("Updated files:")
        for path in changed:
            print(f"- {path}")
    else:
        print("No changes needed.")


if __name__ == "__main__":
    main()
