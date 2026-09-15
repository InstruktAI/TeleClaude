---
description: Momentary dependency highlighting in the Preparation view reveals the visible todo rows that also block the selected todo while leaving its existing tree anchor and layout unchanged.
delivered_by:
  - highlight-hidden-todo-dependencies
---

# Work Queue Dependency Visibility — Spec

## Required reads

@docs/project/spec/feature/workflow/todo-management.md
@docs/project/spec/feature/tui/input-safety.md

## What it is

The Preparation view keeps its existing dependency-tree projection: one dependency may provide the selected todo's visible tree parent while every dependency continues to participate in workflow gating. A human operator can momentarily reveal the other dependency relationships without expanding the row, opening another surface, or changing the tree.

With a todo row selected, uppercase `D` starts a 1.5-second dependency flash. Every currently rendered row in the same project that represents one of the selected todo's dependencies receives the same highlight treatment as a selected todo, except for the dependency already expressed by the selected row's tree parent. That tree parent remains visually unchanged because its connector already exposes the relationship.

The flash is transient view state. It changes no todo data, grouping, dependency order, section visibility, collapse state, cursor selection, or persisted TUI state.

## Canonical fields

### Use cases

#### UC-WQDV1: Flash reveals additional visible dependencies

```gherkin
Given a human operator has selected a todo with multiple dependencies in the Preparation view
And one dependency is already expressed as the selected todo's tree parent
And at least one additional dependency row is currently rendered in the same project
When the operator presses uppercase D
Then every rendered additional dependency row receives the same highlight treatment as a selected todo
And the dependency used as the tree parent is not highlighted
And the selected todo remains selected
And no explanatory row, badge, connector, or other content is added to the tree
```

#### UC-WQDV2: Flash clears without becoming view state

```gherkin
Given a dependency flash is visible
When 1.5 seconds elapse or the operator moves the cursor to another row
Then every dependency highlight is cleared
And the tree returns to its ordinary rendering
And pressing uppercase D again starts a fresh 1.5-second flash for the currently selected todo
```

#### UC-WQDV3: Flash respects the rendered project boundary

```gherkin
Given a selected todo has a dependency whose row is not currently rendered
Or another rendered project contains a todo with the same slug as a dependency
When the operator presses uppercase D
Then the view does not expand a section or project to reveal the hidden row
And no row in another project is highlighted
And every matching dependency row already rendered in the selected todo's project is highlighted according to UC-WQDV1
```
