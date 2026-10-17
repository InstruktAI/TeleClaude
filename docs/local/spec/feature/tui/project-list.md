---
description: The projects the TUI shows per computer — the daemon's project listing,
  redrawn whenever it changes — and adding a project from the TUI by naming only its
  folder.
visibility: internal
---

# Project List — Spec

## Required reads

- @docs/local/spec/feature/config/project-registry.md

## What it is

The TUI's Sessions and Preparation views show, under each computer, the
projects that computer's daemon lists to the viewer: every entry on that
machine's project registry — a project, a person home, or a company home —
whose subject the viewer's reach admits
(`local/projects/teleclaude/spec/feature/identity/data-visibility`), under its display
name, in registry order
(`local/projects/teleclaude/spec/feature/config/project-registry`). Both views redraw when that
list changes, whether or not any session changed with it: a project the daemon
adds, renames, or drops is shown as it now is.

An operator adds a project from the local computer's header in either view by
naming a folder. The new-project action asks for nothing else: the project's
name comes from the folder it adopts. The TUI hands the folder to its daemon,
which adopts it and pushes the new list to every connected TUI
(`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`); the TUI never
sets a project up itself and never runs a command-line tool to do so. While the
daemon works the TUI stays responsive; what the operator is shown when adoption
fails is decided by `local/projects/teleclaude/spec/feature/presentation/work-feedback`.

## Canonical fields

- **Listing.** Per computer, the daemon's project listing for the viewer: display
  name and folder, in registry order, of the registry entries whose subject the
  viewer's reach admits, with the todos each shows. Live updates about an entry
  reach only viewers whose reach admits it.
- **Redraw.** Any change to a computer's listing redraws both views.
- **New-project input.** A folder path. Missing folders are created by the
  daemon's adoption; a path naming a file, or a folder already on the list, is
  refused in the action before it is sent.
- **Reach.** The new-project action is offered on the local computer's header
  only; a project on another computer is adopted on that computer.

### Use cases

#### UC-TUI-PL1: An operator sees each computer's current project list

```gherkin
Scenario: A newly listed project appears even without sessions
  Given an operator is viewing the TUI Sessions view
  When a project with no sessions is added to that computer's project listing
  Then the operator sees the project under its computer
  And nothing else has to change for it to appear

Scenario: A removed or renamed project matches the current listing
  Given an operator is viewing the TUI Sessions view showing a project
  When that project leaves the computer's listing or is listed under a new display name
  Then the operator no longer sees the former row
  And a renamed project appears under its new display name
```

#### UC-TUI-PL3: Adding a project asks only for its folder and shows it everywhere

```gherkin
Given an operator selects the local computer's header in the Sessions or Preparation view
When the operator opens the new-project action and names a folder
Then the action asks for no name and no description
And the operator sees the project in both views under the name its folder gives it
```

#### UC-TUI-PL4: A failed add tells the operator why

#### UC-TUI-PL5: Another computer's header offers no new-project action
