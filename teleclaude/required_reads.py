from __future__ import annotations

import re
from typing import Iterable

_REQUIRED_READS_HEADER = re.compile(r"^##\s+required reads\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_REF_LINE = re.compile(r"^(?:[-*+]\s+)?@(?P<ref>\S+)$")


def extract_required_reads(content: str) -> tuple[list[str], str]:
    """Extract required read refs and remove the section from content."""
    lines = content.splitlines()
    required_refs: list[str] = []
    output: list[str] = []
    in_required = False
    for line in lines:
        stripped = line.strip()
        if not in_required and _REQUIRED_READS_HEADER.match(stripped):
            in_required = True
            continue
        if in_required:
            if stripped.startswith("## "):
                in_required = False
                output.append(line)
                continue
            if not stripped:
                continue
            ref_match = _REQUIRED_REF_LINE.match(stripped)
            if ref_match:
                required_refs.append(ref_match.group("ref"))
                continue
            in_required = False
            output.append(line)
            continue
        output.append(line)
    return required_refs, _join_lines(output)


def strip_required_reads_section(content: str) -> str:
    """Remove the required reads section entirely."""
    lines = content.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line.strip()):
            header_idx = idx
            break
    if header_idx is None:
        return _join_lines(lines)
    section_start = header_idx + 1
    section_end = next(
        (i for i in range(section_start, len(lines)) if _HEADER_LINE.match(lines[i].strip())),
        len(lines),
    )
    output = lines[:header_idx] + lines[section_end:]
    return _join_lines(output)


def normalize_required_refs(refs: Iterable[str]) -> list[str]:
    """Normalize refs, stripping leading '@' when callers include it."""
    normalized: list[str] = []
    for ref in refs:
        clean = ref.strip()
        if clean.startswith("@"):
            clean = clean[1:].strip()
        if clean:
            normalized.append(clean)
    return normalized


def _join_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines).rstrip() + "\n"
