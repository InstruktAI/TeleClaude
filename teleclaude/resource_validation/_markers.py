"""In-body marker validation: liveness, planned-change structure, and grammar.

The fold/reader machinery (``teleclaude.doc_body``) resolves a strict grammar —
whole-line, non-nested, balanced, kebab-slug markers. These validators make the
authoring gate reject exactly what that machinery cannot resolve, so a marker that
validates at ``telec sync`` is always one the delivery fold can fold cleanly.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.doc_body import PLANNED_CHANGE_BLOCK_RE
from teleclaude.resource_validation._models import _CODE_FENCE_LINE, _INLINE_CODE_SPAN, _error

_PLANNED_CHANGE_MARKER_RE = re.compile(
    r"<!--[ \t]*(?P<closing>/)?(?P<kind>planned-change|change):(?P<slug>[^>\s]+)[ \t]*-->"
)
_PLANNED_MARKER_RE = re.compile(r"<!--[ \t]*(?P<closing>/)?planned:(?P<slug>[^>\s]+)[ \t]*-->")
_PLANNED_CHANGE_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
# Broad detector for every in-body marker kind, position-independent and with a
# permissive slug, so malformed structures are surfaced rather than skipped. Order
# matters: ``planned-change`` precedes ``planned`` so the longer literal wins.
_MARKER_RE = re.compile(r"<!--[ \t]*(?P<closing>/)?(?P<kind>planned-change|planned|change):(?P<slug>[^>\s]+)[ \t]*-->")

# A pending in-body marker (or delivered_by entry) is reported only when its slug
# resolves to an already-delivered todo — a marker delivery should have folded but
# did not. An active/icebox/removed todo is in flight and tolerated; a slug absent
# from the local store is expected and skipped, since todos are machine-local and a
# git-carried snippet routinely names a todo that lives on another computer.
_RESOLVABLE_TODO_STATUSES = frozenset({TodoStatus.ACTIVE.value, TodoStatus.ICEBOX.value, TodoStatus.REMOVED.value})


def _inside_any_span(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _planned_change_marker_error(path: Path, marker: re.Match[str], reason: str) -> None:
    _error(
        "snippet_planned_change_marker_invalid",
        path=str(path),
        marker=marker.group(0),
        reason=reason,
    )


def _mask_fenced_code_blocks(text: str) -> str:
    lines: list[str] = []
    in_code_block = False
    for line in text.splitlines(keepends=True):
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            lines.append(line)
            continue
        lines.append("\n" if in_code_block else line)
    return "".join(lines)


def _mask_inline_code_spans(text: str) -> str:
    def _blank(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    return "".join(_INLINE_CODE_SPAN.sub(_blank, line) for line in text.splitlines(keepends=True))


def _mask_marker_examples(body: str) -> str:
    return _mask_inline_code_spans(_mask_fenced_code_blocks(body))


def _validate_planned_marker_liveness(
    path: Path,
    body: str,
    todo_status_map: Mapping[str, str],
) -> None:
    checked_slugs: set[str] = set()
    for marker in [*_PLANNED_CHANGE_MARKER_RE.finditer(body), *_PLANNED_MARKER_RE.finditer(body)]:
        slug = marker.group("slug")
        if slug in checked_slugs:
            continue
        checked_slugs.add(slug)
        status = todo_status_map.get(slug)
        # Unknown slug (no local row) is expected — todos are machine-local; only a
        # delivered slug is a real stale marker (delivery should have folded it).
        if status in _RESOLVABLE_TODO_STATUSES or status is None:
            continue
        _error(
            "snippet_planned_marker_invalid_slug", path=str(path), slug=slug, reason=f"todo is {status}, not in flight"
        )


def validate_planned_change_markers(
    path: Path,
    body: str,
    todo_status_map: Mapping[str, str] | None = None,
) -> None:
    body = _mask_marker_examples(body)
    if todo_status_map is not None:
        _validate_planned_marker_liveness(path, body, todo_status_map)
    valid_spans = [match.span() for match in PLANNED_CHANGE_BLOCK_RE.finditer(body)]
    markers = [
        marker
        for marker in _PLANNED_CHANGE_MARKER_RE.finditer(body)
        if not _inside_any_span(marker.start(), valid_spans)
    ]
    idx = 0
    while idx < len(markers):
        open_marker = markers[idx]
        open_slug = open_marker.group("slug")
        if not _PLANNED_CHANGE_SLUG_RE.fullmatch(open_slug):
            _planned_change_marker_error(path, open_marker, "slug must be kebab-case")
        if open_marker.group("kind") != "planned-change" or open_marker.group("closing"):
            _planned_change_marker_error(path, open_marker, "marker appears outside a planned-change block")
            idx += 1
            continue

        if idx + 1 >= len(markers):
            _planned_change_marker_error(path, open_marker, "missing change separator and closing marker")
            break
        separator = markers[idx + 1]
        if separator.group("kind") != "change" or separator.group("closing"):
            _planned_change_marker_error(path, open_marker, "missing change separator")
            idx += 2 if separator.group("kind") == "planned-change" and separator.group("closing") else 1
            continue
        if not _PLANNED_CHANGE_SLUG_RE.fullmatch(separator.group("slug")):
            _planned_change_marker_error(path, separator, "slug must be kebab-case")
        if separator.group("slug") != open_slug:
            _planned_change_marker_error(path, separator, f"separator slug does not match {open_slug}")

        if idx + 2 >= len(markers):
            _planned_change_marker_error(path, open_marker, "missing closing marker")
            break
        close_marker = markers[idx + 2]
        if close_marker.group("kind") != "planned-change" or not close_marker.group("closing"):
            _planned_change_marker_error(path, open_marker, "missing closing marker")
            idx += 2
            continue
        if not _PLANNED_CHANGE_SLUG_RE.fullmatch(close_marker.group("slug")):
            _planned_change_marker_error(path, close_marker, "slug must be kebab-case")
        if close_marker.group("slug") != open_slug:
            _planned_change_marker_error(path, close_marker, f"closing slug does not match {open_slug}")
        idx += 3


def _marker_is_own_line(body: str, marker: re.Match[str]) -> bool:
    """True when only whitespace precedes the marker and follows it on its line."""
    line_start = body.rfind("\n", 0, marker.start()) + 1
    line_end = body.find("\n", marker.end())
    if line_end == -1:
        line_end = len(body)
    before = body[line_start : marker.start()]
    after = body[marker.end() : line_end]
    return not before.strip() and not after.strip()


def validate_marker_structure(path: Path, body: str) -> None:
    """Reject in-body markers the single-pass delivery fold cannot resolve.

    The fold/reader grammar is whole-line and non-nested; this makes the
    validator's accepted grammar equal it. For every ``planned`` /
    ``planned-change`` / ``change`` marker it enforces:

    - **Own-line** — a marker sharing its line with prose (``snippet_marker_not_line_level``).
    - **No nesting** — a block opening while another is still open
      (``snippet_marker_nested``); on overlap, dependency-order the todos instead.
    - **Balance** for ``planned`` ADD blocks — an orphaned close or an unclosed
      open (``snippet_marker_unbalanced``); ``planned-change`` balance stays owned
      by :func:`validate_planned_change_markers`.
    - **Kebab slug** for ``planned`` ADD markers (``snippet_marker_invalid_slug``);
      ``planned-change`` / ``change`` kebab stays owned by that same validator.

    Code-fence and inline-code examples are masked, so syntax samples never flag.
    """
    body = _mask_marker_examples(body)
    open_stack: list[tuple[str, str, str]] = []
    for marker in _MARKER_RE.finditer(body):
        kind = marker.group("kind")
        slug = marker.group("slug")
        closing = bool(marker.group("closing"))

        if not _marker_is_own_line(body, marker):
            _error("snippet_marker_not_line_level", path=str(path), marker=marker.group(0))

        if kind == "change":
            # ``change`` is the planned-change mid-separator (and ``/change`` is not a
            # real form); it neither opens nor closes a block here.
            continue

        if kind == "planned" and not _PLANNED_CHANGE_SLUG_RE.fullmatch(slug):
            _error(
                "snippet_marker_invalid_slug",
                path=str(path),
                marker=marker.group(0),
                reason="slug must be kebab-case",
            )

        if not closing:
            if open_stack:
                _error(
                    "snippet_marker_nested",
                    path=str(path),
                    marker=marker.group(0),
                    enclosing=open_stack[-1][2],
                )
            open_stack.append((kind, slug, marker.group(0)))
            continue

        if open_stack and open_stack[-1][0] == kind and open_stack[-1][1] == slug:
            open_stack.pop()
            continue
        if kind == "planned":
            _error(
                "snippet_marker_unbalanced",
                path=str(path),
                marker=marker.group(0),
                reason="closing marker has no matching open block",
            )

    for kind, _, open_text in open_stack:
        if kind == "planned":
            _error(
                "snippet_marker_unbalanced",
                path=str(path),
                marker=open_text,
                reason="block is never closed",
            )
