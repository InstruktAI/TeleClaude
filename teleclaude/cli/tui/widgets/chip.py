"""Person chip resolution for TUI rows.

A person chip is the owning human's uppercase initials painted in that person's
configured colors. The daemon projects the person's display facts onto each row;
one builder feeds both the todo-row and session-row renderers so initials and
color fallback stay consistent. Unset color cells fall back to the
theme-derived neutral defaults for the active mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style

from teleclaude.api_models_identity import ChipColorPairDTO, OwnershipSurfaceDTO, PersonChipDTO
from teleclaude.cli.tui.theme import get_neutral_color, get_selection_fg_hex, is_dark_mode
from teleclaude.types.creation_record import SYSTEM_ROOT_PREFIX

_HUMAN_PRINCIPAL_PREFIX = "human:"
_SYSTEM_CHIP_INITIALS = "S"
_BLACK_HEX = "#000000"
_WHITE_HEX = "#ffffff"


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
    custom_background: bool

    def style(self, *, selected: bool = False, inverted: bool = False) -> Style:
        """Rich style for the chip.

        Weight encodes selection alone: a selected/previewed row's chip is bold,
        every other state is normal weight. Color encodes on/off: at rest the chip
        shows its resolved low-contrast colors; once active — its person is the
        live filter (on), or its row is highlighted — it takes the row's selection
        text pole (black in dark mode, white in light) over its fill, a custom hue
        kept and a neutral chip using the opposite pole (the sticky-badge look).
        """
        if selected or inverted:
            text = get_selection_fg_hex()
            neutral_bg = _BLACK_HEX if text == _WHITE_HEX else _WHITE_HEX
            background = self.background if self.custom_background else neutral_bg
            return Style(color=text, bgcolor=background, bold=selected)
        return Style(color=self.text, bgcolor=self.background)


@dataclass(frozen=True)
class SystemChip:
    """The system-root owner chip, which does not select a human filter."""

    initials: str = _SYSTEM_CHIP_INITIALS
    person_email: None = None

    def style(self, *, selected: bool = False, inverted: bool = False) -> Style:
        """Use neutral owner colors while preserving row selection contrast."""
        background, text, _custom_background = _chip_colors(None)
        if selected or inverted:
            text = get_selection_fg_hex()
            background = _BLACK_HEX if text == _WHITE_HEX else _WHITE_HEX
            return Style(color=text, bgcolor=background, bold=selected)
        return Style(color=text, bgcolor=background)


type OwnerChip = PersonChip | SystemChip


def _color_cell(pair: ChipColorPairDTO | None, *, dark: bool) -> str | None:
    """Read one theme-split color cell, or None when unset."""
    if pair is None:
        return None
    return pair.dark if dark else pair.light


def _chip_colors(chip: PersonChipDTO | None) -> tuple[str, str, bool]:
    """Resolve (background, text, custom_background) from cells and theme defaults.

    The resting chip is a low-contrast fill: the neutral ``subtle`` background
    (light grey in light mode, dark grey in dark mode — nearest the terminal
    background) under the neutral ``highlight`` text. A set cell is always honored
    verbatim. ``custom_background`` reports whether the background came from a
    per-person cell rather than the neutral default — a selected chip keeps a
    custom hue but pushes a neutral default to its pole. See ``PersonChip.style``.
    """
    dark = is_dark_mode()
    background_cell = _color_cell(chip.background if chip else None, dark=dark)
    background = background_cell or get_neutral_color("subtle")
    text = _color_cell(chip.text if chip else None, dark=dark) or get_neutral_color("highlight")
    return background, text, background_cell is not None


@dataclass
class _OwnershipSurfaceHolder:
    enabled: bool = False


_OWNERSHIP_SURFACE = _OwnershipSurfaceHolder()


def adopt_ownership_surface(surface: OwnershipSurfaceDTO) -> bool:
    """Take the daemon's ownership-surface fact, which chips and the filter follow; True when it changed."""
    changed = _OWNERSHIP_SURFACE.enabled != surface.enabled
    _OWNERSHIP_SURFACE.enabled = surface.enabled
    return changed


def ownership_surface_enabled() -> bool:
    """True when the owner chips and per-human filter should render.

    The ownership surface is multi-user-gated: with a sole registered person
    there is no ownership to disambiguate, so chips and the filter are
    suppressed. The daemon projects that determination; it is off until it has.
    """
    return _OWNERSHIP_SURFACE.enabled


def build_owner_chip(owner: str | None, person_chip: PersonChipDTO | None) -> OwnerChip | None:
    """Build the owner chip of a row from its owner and the person facts the daemon projected onto it.

    ``owner`` is a lineage root, a human principal, or a bare email. Returns
    ``None`` when the human is unresolvable (no owner, or no person facts on the
    row) or when the ownership surface is suppressed (single-user mode) — the row
    renders no chip and closes the gap rather than reserving width.
    """
    if not owner or not ownership_surface_enabled():
        return None
    if owner.startswith(SYSTEM_ROOT_PREFIX):
        return SystemChip()
    email = principal_to_email(owner)
    if not email or person_chip is None:
        return None
    background, text, custom_background = _chip_colors(person_chip)
    return PersonChip(
        initials=person_chip.initials,
        person_email=email.lower(),
        background=background,
        text=text,
        custom_background=custom_background,
    )
