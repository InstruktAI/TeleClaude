---
description: 'Todo-row column alignment contract for the TUI preparation view: one shared property-column offset derived from the longest slug, gap compression before slug truncation, ellipsized over-budget slugs, and a state column that renders intact at and above the structural minimum pane width.'
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
offset, identical for every row regardless of tree depth. On a pane wide enough
for the longest slug plus the widest column block, that offset derives from the
longest slug across the rendered set and every slug renders in full with at
least one dot leader. When the pane narrows, the layout degrades in a fixed
order — the slug-to-column gap compresses first, uniformly for all rows; slugs
that no longer fit the shared budget truncate with a trailing ellipsis; the
column block and the state column never shift per-row. The shared offset never
compresses past the structural minimum, so a slug always retains at least an
ellipsis cell and one dot leader.

The state column and the trailing right gutter render intact at every pane
width at or above the structural minimum. Below that minimum the fixed regions
themselves exceed the pane: rows keep the shared column offset and truncate
best-effort at the right edge, outside this contract's intact-state-column
guarantee.

## Canonical fields

### Structural minimum width

The pane width at which a row's fixed regions exactly fit: the deepest tree
prefix, a one-cell slug ellipsis, one dot leader, the widest property-column
block including the state column, and the trailing right gutter. The
intact-state-column guarantee binds at and above this width; the shared-offset
invariant binds at every width.

### Use cases

#### UC-TRA1: A narrow pane keeps one shared column offset and an intact state column

```
Given todos with slugs of differing lengths and tree depths render in the preparation view
And the pane is narrower than the longest slug plus the widest column block plus separators
And the pane is at or above the structural minimum width
When the rows render
Then every row's property column block starts at the same cell offset
And a slug that exceeds the shared budget truncates with a trailing ellipsis followed by at least one dot leader
And a slug that fits the shared budget renders in full
And every row's schedule badge, owner chip, autonomous-filing marker, and hold glyph occupy their reserved cells
And every row ends at the same right gutter
```
