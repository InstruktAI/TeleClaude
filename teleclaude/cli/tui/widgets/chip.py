"""Person chip resolution for TUI rows.

A person chip is the owning human's uppercase initials painted in that person's
configured colors. One resolver feeds both the todo-row and session-row
renderers so initials and color fallback stay consistent. Unset color cells fall
back to the theme-derived neutral defaults for the active mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style

from teleclaude.cli.tui.theme import get_neutral_color, is_dark_mode
from teleclaude.config.schema import PersonChipColor
from teleclaude.core.identity import derive_initials, get_identity_resolver

_HUMAN_PRINCIPAL_PREFIX = "human:"


def principal_to_email(principal: str | None) -> str | None:
    """Extract the email from a ``human:<email>`` principal or a bare email."""
    if not principal:
        return None
    value = principal.strip()
    if value.startswith(_HUMAN_PRINCIPAL_PREFIX):
        value = value[len(_HUMAN_PRINCIPAL_PREFIX) :]
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class PersonChip:
    """A resolved owner chip: initials, the owning email, and its colors."""

    initials: str
    person_email: str
    background: str
    text: str

    def style(self, *, inverted: bool = False) -> Style:
        """Rich style for the chip; inverted swaps background and text."""
        if inverted:
            return Style(color=self.background, bgcolor=self.text, bold=True)
        return Style(color=self.text, bgcolor=self.background, bold=True)


def _color_cell(color: PersonChipColor | None, attr: str, *, dark: bool) -> str | None:
    """Read one theme-split color cell, or None when unset."""
    if color is None:
        return None
    pair = getattr(color, attr)
    return pair.dark if dark else pair.light


def _chip_colors(color: PersonChipColor | None) -> tuple[str, str]:
    """Resolve (background, text), filling unset cells from the theme defaults.

    The theme-derived defaults are the neutral standard-grey background and the
    neutral highlight text for the active mode. A set cell is always honored
    verbatim.
    """
    dark = is_dark_mode()
    background = _color_cell(color, "background", dark=dark) or get_neutral_color("normal")
    text = _color_cell(color, "text", dark=dark) or get_neutral_color("highlight")
    return background, text


def ownership_surface_enabled() -> bool:
    """True when the owner chips and per-human filter should render.

    The ownership surface is multi-user-gated: with a sole registered person
    there is no ownership to disambiguate, so chips and the filter are
    suppressed. Reads the one shared multi-user determination.
    """
    return get_identity_resolver().is_multi_user


def resolve_person_chip(principal: str | None) -> PersonChip | None:
    """Resolve the owner chip for a todo/session principal.

    Returns ``None`` when the human is unresolvable (no principal, or an email
    that matches no registered person) or when the ownership surface is
    suppressed (single-user mode) — the row renders no chip and closes the gap
    rather than reserving width. The cheap principal check runs first so a
    chip-less row never touches the identity resolver.
    """
    email = principal_to_email(principal)
    if not email:
        return None
    if not ownership_surface_enabled():
        return None
    context = get_identity_resolver().resolve_by_email(email)
    if not context.person_name:
        return None
    initials = derive_initials(context.person_name)
    if not initials:
        return None
    background, text = _chip_colors(context.chip_color)
    return PersonChip(initials=initials, person_email=email.lower(), background=background, text=text)
