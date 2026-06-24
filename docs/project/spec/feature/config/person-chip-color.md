---
description: Per-person overlay color schema — an optional four-cell background/text
  × light/dark structure backing the person chip, stored on PersonConfig so personalization
  stays in the person-owned overlay.
---

# Person Chip Color — Spec

## What it is

A person's display color personalizes the person chip the TUI paints for their
todos and sessions. It lives on the per-person overlay (`PersonConfig.color`),
not the global `PersonEntry`, so the global `people` list stays admin-governed
while a person's own appearance settings live in their person-owned overlay
folder.

The field is a nested, fully optional structure carrying a background and a text
color, each split by theme mode:

```
PersonConfig.color:                  # whole block optional
  background:
    light: str | None
    dark:  str | None
  text:
    light: str | None
    dark:  str | None
```

Every cell is independently optional and defaults to `None`. `None` is not a
stored color — it is the signal that the renderer supplies the theme-derived
default for the active mode (see `todo-session-cross-navigation` for the chip
render and the concrete defaults). A set cell is honored verbatim; nothing
overrides it. Because every cell is operator-set, color contrast is the
operator's responsibility.

Both nested models carry default-instance factories so the parent
`PersonConfig.color` can be instantiated with an empty tree, and a single leaf
can be set without pre-populating its siblings — the per-person overlay save
path instantiates the missing intermediate models on demand.

## Canonical fields

### Allowed values

- `color` — optional `PersonChipColor`. Default: `None` (the whole block absent).
- `color.background.light` / `color.background.dark` — optional color string per theme mode. Default: `None`.
- `color.text.light` / `color.text.dark` — optional color string per theme mode. Default: `None`.

### Use cases

#### UC-CHIP-COLOR-1: Whole block absent is the default

```
Given a PersonConfig with no color key
When PersonConfig validation runs
Then color is None
And the entry is accepted
```

#### UC-CHIP-COLOR-2: A single cell sets without its siblings

```
Given a PersonConfig where only color.background.light is provided
When PersonConfig validation runs
Then the color block instantiates with background.light set
And background.dark, text.light, and text.dark each remain None
And the entry is accepted
```

#### UC-CHIP-COLOR-3: Color cells are editable in the People subtab

```
Given the Configuration People subtab has a person expanded
When the per-person overlay is reflected into the Overlay Settings section
Then the four color leaves (background.light, background.dark, text.light, text.dark) appear as editable fields even when color is unset
And editing a leaf instantiates the nested color models on demand
And the value persists to the person's overlay file
```

#### UC-CHIP-COLOR-4: A set cell is stored verbatim

```
Given a PersonConfig with color.text.dark set to a color string
When PersonConfig validation runs and the value is persisted
Then the stored color.text.dark equals the provided string unchanged
```

## Known caveats

- **No contrast validation.** Any color string is accepted per cell; a poor
  background/text pairing can render an unreadable chip. The renderer never
  auto-corrects a set cell.
- **`None` means renderer-default, not "no color."** An unset cell is filled at
  render time with the theme-derived default; it is never stored as a concrete
  color.

## See Also

- docs/project/spec/feature/tui/todo-session-cross-navigation.md — how the chip
  is rendered from these cells, the theme-derived defaults for unset cells, and
  the bidirectional todo↔session navigation the chip participates in.
