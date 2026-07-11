---
description: 'Todo-row column alignment contract for the TUI preparation view: one shared property-column offset derived from the longest slug at every pane width, gap compression before truncation, ellipsized over-budget slugs, and a state column that never truncates.'
visibility: 'public'
delivered_by:
  - tui-todo-columns-misalign-on-narrow-pane
---

# Todo Row Alignment — Spec

## Required reads

- @docs/project/design/architecture/tui-state-layout.md

## What it is

Every todo row in the preparation view renders four regions left to right: the
tree prefix (indent, connectors, status glyph), the slug with dot leaders, the
property column block (kind plus phase/work columns), and the fixed-width state
column (schedule badge, owner chip, autonomous-filing marker, hold glyph).

The alignment contract is a single invariant: all rows share one property-column
offset, derived from the longest slug across the rendered set and identical for
every row regardless of tree depth. When the pane narrows, the layout degrades
in a fixed order — the slug-to-column gap compresses first, uniformly for all
rows; slugs that no longer fit their budget truncate with an ellipsis; the
column block and the state column never shift per-row and never truncate. Slug
truncation engages only when the longest slug plus the widest column block plus
separators genuinely exceed the available width.

## Canonical fields

### Use cases

#### UC-TRA1: Property columns align to the longest slug

```
Given todos with slugs of differing lengths and tree depths render in the preparation view
And the pane is wide enough for the longest slug plus the widest column block
When the rows render
Then every row's property column block starts at the same cell offset
And that offset is derived from the longest slug across all rendered todos
And every slug renders in full
And every slug is separated from its columns by at least one dot leader
```

#### UC-TRA2: A narrow pane keeps a shared column offset

```
Given the pane is narrower than the longest slug plus the widest column block plus separators
When the rows render
Then the shared column offset is reduced uniformly for all rows
And every row's property column block still starts at that same offset
And no row's columns shift right relative to any other row
```

#### UC-TRA3: Only over-budget slugs truncate, with an ellipsis

```
Given the shared column offset leaves a row less room than its slug needs
When that row renders
Then the slug is truncated with a trailing ellipsis inside the shared slug budget
And at least one dot leader separates the truncated slug from its columns
And rows whose slugs fit their budget render those slugs in full
```

#### UC-TRA4: The state column and right gutter survive every width

```
Given any pane width and any slug length
When a row renders
Then the schedule badge, owner chip, autonomous-filing marker, and hold glyph occupy their reserved cells
And none of those cells are truncated away
And every row ends at the same right gutter
```
