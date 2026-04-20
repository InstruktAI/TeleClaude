"""Helpers for collapsing adjacent styled cells into shared Rich text runs."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

Cell = tuple[str, str | None, str | None]
_StyleKey = tuple[str | None, str | None]
_STYLE_CACHE: dict[_StyleKey, Style | None] = {}


def _cached_style(fg: str | None, bg: str | None) -> Style | None:
    key = (fg, bg)
    style = _STYLE_CACHE.get(key)
    if key in _STYLE_CACHE:
        return style
    resolved = Style(color=fg, bgcolor=bg) if fg or bg else None
    _STYLE_CACHE[key] = resolved
    return resolved


def append_cells(text: Text, cells: list[Cell]) -> None:
    """Append cells while collapsing adjacent identical styles into one span."""
    if not cells:
        return

    chars: list[str] = []
    current_key: _StyleKey | None = None

    for char, fg, bg in cells:
        key = (fg, bg)
        if current_key is None:
            current_key = key
        elif key != current_key:
            _append_run(text, chars, current_key)
            chars = []
            current_key = key
        chars.append(char)

    if current_key is not None:
        _append_run(text, chars, current_key)


def _append_run(text: Text, chars: list[str], key: _StyleKey) -> None:
    content = "".join(chars)
    style = _cached_style(*key)
    if style is None:
        text.append(content)
    else:
        text.append(content, style=style)
