"""Pure transforms over documentation-snippet bodies.

These helpers operate on raw snippet text — splitting frontmatter, expanding
inline ``@path`` references, and resolving ``<!-- planned:slug -->`` blocks — with
no dependency on the snippet index or model, so they stay reusable and testable
in isolation from the context selector that orchestrates them.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "INLINE_REF_RE",
    "PLANNED_BLOCK_RE",
    "PLANNED_CHANGE_BLOCK_RE",
    "apply_planned_change_sections",
    "apply_planned_sections",
    "resolve_inline_refs",
    "resolve_planned_change_for_delivery",
    "split_frontmatter",
    "strip_planned_markers",
]

INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")

PLANNED_BLOCK_RE = re.compile(
    r"[ \t]*<!--[ \t]*planned:(?P<slug>[a-z0-9-]+)[ \t]*-->[ \t]*\n"
    r"(?P<content>.*?)"
    r"[ \t]*<!--[ \t]*/planned:(?P=slug)[ \t]*-->[ \t]*\n?",
    re.DOTALL,
)

PLANNED_CHANGE_BLOCK_RE = re.compile(
    r"[ \t]*<!--[ \t]*planned-change:(?P<slug>[a-z0-9-]+)[ \t]*-->[ \t]*\n"
    r"(?P<current>.*?)"
    r"[ \t]*<!--[ \t]*change:(?P=slug)[ \t]*-->[ \t]*\n"
    r"(?P<replacement>.*?)"
    r"[ \t]*<!--[ \t]*/planned-change:(?P=slug)[ \t]*-->[ \t]*\n?",
    re.DOTALL,
)

# Inline variants: markers embedded mid-line (e.g. a planned-change replacing a
# clause inside a sentence) cannot be own-line wrapped without breaking prose.
# These match the marker comments only — no surrounding whitespace/newline is
# consumed — so the body reads verbatim once the comments are removed. Applied as
# a second pass after the own-line patterns, which have already removed full
# marker lines, so only genuinely inline markers remain.
_INLINE_PLANNED_BLOCK_RE = re.compile(
    r"<!--[ \t]*planned:(?P<slug>[a-z0-9-]+)[ \t]*-->(?P<content>.*?)<!--[ \t]*/planned:(?P=slug)[ \t]*-->",
    re.DOTALL,
)

_INLINE_PLANNED_CHANGE_BLOCK_RE = re.compile(
    r"<!--[ \t]*planned-change:(?P<slug>[a-z0-9-]+)[ \t]*-->(?P<current>.*?)"
    r"<!--[ \t]*change:(?P=slug)[ \t]*-->(?P<replacement>.*?)"
    r"<!--[ \t]*/planned-change:(?P=slug)[ \t]*-->",
    re.DOTALL,
)


def split_frontmatter(content: str) -> tuple[str, str]:
    """Split frontmatter header from body, preserving header verbatim."""
    if not content.startswith("---"):
        return "", content
    lines = content.splitlines(keepends=True)
    if not lines:
        return "", content
    # Find the closing frontmatter fence.
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            head = "".join(lines[: idx + 1])
            body = "".join(lines[idx + 1 :])
            return head, body
    return "", content


def resolve_inline_refs(content: str, *, snippet_path: Path, root_path: Path) -> str:
    """Expand @<path>.md references to absolute paths for tool consumption."""
    head, body = split_frontmatter(content)

    def _expand(match: re.Match[str]) -> str:
        ref = match.group(1)
        if "://" in ref:
            return match.group(0)
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            if str(candidate).startswith("docs/"):
                candidate = (root_path / candidate).resolve()
            else:
                candidate = (snippet_path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return f"@{candidate}"

    return f"{head}{INLINE_REF_RE.sub(_expand, body)}"


def apply_planned_sections(body: str, target_slug: str | None) -> str:
    """Resolve ``<!-- planned:slug -->`` blocks for the reader's lens.

    Plain reads drop every planned block — the live contract carries no pending
    content. A ``--target slug`` read keeps that slug's blocks (markers stripped,
    body in place) and drops every other slug's, so the builder sees the parent
    exactly as it will read once its own work lands.
    """

    def _resolve(match: re.Match[str]) -> str:
        if target_slug is not None and match.group("slug") == target_slug:
            return match.group("content")
        return ""

    body = PLANNED_BLOCK_RE.sub(_resolve, body)
    return _INLINE_PLANNED_BLOCK_RE.sub(_resolve, body)


def apply_planned_change_sections(body: str, target_slug: str | None) -> str:
    """Resolve ``<!-- planned-change:slug -->`` blocks for the reader's lens."""

    def _resolve(match: re.Match[str]) -> str:
        if target_slug is not None and match.group("slug") == target_slug:
            return match.group("replacement")
        return match.group("current")

    body = PLANNED_CHANGE_BLOCK_RE.sub(_resolve, body)
    return _INLINE_PLANNED_CHANGE_BLOCK_RE.sub(_resolve, body)


def resolve_planned_change_for_delivery(text: str, slug: str) -> str:
    """Make ``slug``'s planned-change replacements live while preserving other slugs."""

    def _resolve(match: re.Match[str]) -> str:
        if match.group("slug") == slug:
            return match.group("replacement")
        return match.group(0)

    text = PLANNED_CHANGE_BLOCK_RE.sub(_resolve, text)
    return _INLINE_PLANNED_CHANGE_BLOCK_RE.sub(_resolve, text)


def strip_planned_markers(text: str, slug: str) -> str:
    """Drop a slug's ``<!-- planned:slug -->`` marker lines, keeping their content.

    The delivery-side counterpart to :func:`apply_planned_sections`: once the slug is
    delivered, its planned content becomes part of the live contract, so only the
    bracketing comment lines are removed. Own-line markers take their whole line;
    inline markers (mid-prose) drop only the comment, leaving the body verbatim.
    """
    own_line = re.compile(rf"[ \t]*<!--[ \t]*/?planned:{re.escape(slug)}[ \t]*-->[ \t]*\n")
    inline = re.compile(rf"<!--[ \t]*/?planned:{re.escape(slug)}[ \t]*-->")
    return inline.sub("", own_line.sub("", text))
