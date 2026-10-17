---
description: Momentary dependency highlighting in the Preparation view reveals the
  visible todo rows that also block the selected todo while leaving its existing tree
  anchor and layout unchanged.
---

# Work Queue Dependency Visibility — Spec

## Required reads

@docs/local/spec/feature/workflow/todo-management.md
@docs/local/spec/feature/tui/input-safety.md
@docs/local/spec/feature/tui/todo-session-cross-navigation.md

## What it is

The Preparation view keeps its existing dependency-tree projection: one dependency may provide the selected todo's visible tree parent while every dependency continues to participate in workflow gating. A human operator can momentarily reveal the other dependency relationships without expanding the row, opening another surface, or changing the tree.

With a todo row selected, uppercase `D` starts a 1.5-second dependency flash. Every currently rendered row in the same project that represents one of the selected todo's dependencies takes the selected row's slug highlight, except for the dependency already expressed by the selected row's tree parent. That tree parent remains visually unchanged because its connector already exposes the relationship.

The flash marks the row's slug span only. Owner-chip weight continues to track selection and preview alone, so a flashed row that is not selected keeps its ordinary chip weight.

A project is identified by its computer and path together. A row that is mounted but not displayed is not a rendered row.

The flash is transient view state. It changes no todo data, grouping, dependency order, section visibility, collapse state, cursor selection, or persisted TUI state.

## Canonical fields

### Use cases

#### UC-WQDV1: An operator sees the selected todo's other dependencies

```gherkin
Scenario: The dependency flash reveals other visible dependencies without changing the tree
  Given a human operator has selected a todo with multiple dependencies in the Preparation view
  And one dependency is already expressed as the selected todo's tree parent
  And at least one additional dependency row is currently rendered in the same project
  When the operator reveals the dependencies
  Then every rendered additional dependency row is highlighted
  And the owner-chip weight of an unselected highlighted row is unchanged
  And the tree parent is not highlighted
  And the selected todo and existing tree layout remain unchanged

Scenario: The dependency flash is momentary
  Given a dependency highlight is visible
  When 1.5 seconds elapse or the operator selects another row
  Then the highlights clear and the tree returns to its ordinary rendering
  And revealing dependencies again starts a fresh flash for the selected todo

Scenario: The flash stays within the visible project
  Given a dependency row is hidden by a filter or collapsed section
  Or another computer has a project at the same path with a todo sharing the dependency slug
  When the operator reveals the selected todo's dependencies
  Then no hidden row is revealed or highlighted
  And no row in the other project is highlighted
  And every matching dependency row already rendered in the selected todo's project is highlighted
```

#### UC-WQDV2: Flash clears without becoming view state

#### UC-WQDV3: Flash respects the rendered project boundary
