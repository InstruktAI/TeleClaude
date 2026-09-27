---
description: The projects the TUI shows per computer — the daemon's project listing, redrawn whenever it changes — and adding a project from the TUI by naming only its folder.
visibility: internal
delivered_by:
  - single-project-registry
---

# Project List — Spec

## Required reads

- @docs/project/spec/feature/config/project-registry.md

## What it is

The TUI's Sessions and Preparation views show, under each computer, the
projects that computer's daemon lists: every entry on that machine's project
registry, under its display name, in registry order
(`project/spec/feature/config/project-registry`). Both views redraw when that
list changes, whether or not any session changed with it: a project the daemon
adds, renames, or drops is shown as it now is.

An operator adds a project from the local computer's header in either view by
naming a folder. The new-project action asks for nothing else: the project's
name comes from the folder it adopts. The TUI hands the folder to its daemon,
which adopts it and pushes the new list to every connected TUI; the TUI never
sets a project up itself and never runs a command-line tool to do so. While the
daemon works the TUI stays responsive, and when adoption fails the operator
sees the daemon's reason.

## Canonical fields

- **Listing.** Per computer, the daemon's project listing: display name and
  folder, in registry order.
- **Redraw.** Any change to a computer's listing redraws both views.
- **New-project input.** A folder path. Missing folders are created by the
  daemon's adoption; a path naming a file, or a folder already on the list, is
  refused in the action before it is sent.
- **Reach.** The new-project action is offered on the local computer's header
  only; a project on another computer is adopted on that computer.

### Use cases

#### UC-TUI-PL1: A newly listed project with no sessions appears in the Sessions view

```gherkin
Given an operator is viewing the TUI Sessions view
And a project with no sessions is added to that computer's project listing
When the daemon pushes the updated listing
Then the operator sees that project under its computer within seconds
And nothing else had to change for it to appear
```

#### UC-TUI-PL2: A project the listing drops or renames is redrawn as it now is

```gherkin
Given an operator is viewing the TUI Sessions view showing a project
When that project leaves the computer's listing or is listed under a new display name
Then the operator no longer sees the project's former row
And a renamed project is shown under its new display name
```

#### UC-TUI-PL3: Adding a project asks only for its folder and shows it everywhere

```gherkin
Given an operator selects the local computer's header in the Sessions or Preparation view
When the operator opens the new-project action and names a folder
Then the action asks for no name and no description
And the operator sees the project in both views under the name its folder gives it
And the daemon did not restart
```

#### UC-TUI-PL4: A failed add tells the operator why

```gherkin
Given an operator names a folder in the new-project action
When the daemon refuses or fails to adopt it
Then the operator sees the daemon's reason in the TUI
And no new project appears in either view
```

#### UC-TUI-PL5: Another computer's header offers no new-project action

```gherkin
Given an operator selects a remote computer's header in the Sessions or Preparation view
When the operator invokes the new-project action
Then no new-project input opens
And the operator is told that a project is added on its own computer
```
