---
description: A GitHub-backed project's work shown on one organization-owned GitHub
  Projects board, every item in its lane and the items that need a person in their
  own view, kept true by the platform from the workflow record and never moved by
  hand.
---

# Workflow Board — Spec

## Required reads

- @docs/local/spec/domain/workflow.md
- @docs/local/spec/feature/workflow/github-work-record.md

## What it is

A project on the GitHub workflow store
(`local/projects/teleclaude/spec/feature/workflow/github-work-record`) whose
repository belongs to an organization has one GitHub Projects board, owned by
that organization and linked to the repository. The board shows the project's
work at a glance: each work item in the lane it is in, and a view of the items
that are waiting on a person.

**Business value:** the person running a project sees where all of its work
stands, and what is waiting on them, in one place on GitHub, without asking an
agent, running TeleClaude or opening issues one by one.

The board is a reflection of the workflow record. The platform App that writes
the record keeps the board true from the same changes that move the work; no
agent and no person moves an item on it, and nothing on the board is ever read
back as workflow state.

## Canonical fields

- **Board:** the platform creates the board, titled with the repository's
  name, the first time a computer serving the project refreshes it from
  GitHub. A project never gets a second board: when several computers serve
  it, exactly one of them creates the board and every other one uses it, and a
  board someone deleted is created again the same way. It links the board to the repository as soon as the platform App can read the
  repository's contents; a board someone linked by hand is already linked. The
  App keeps the board with the organization's Projects read and write
  permission and links it with the repository's Contents read permission
  (`local/projects/teleclaude/design/architecture/workflow-store`).
- **Items:** every work item the project's GitHub store holds that is active,
  iceboxed or delivered is an item on the board, from the moment the store
  creates it. A removed item leaves the board, and a reactivated item returns
  to it. A group holder is context for its children, not an item with a lane
  of its own (`local/projects/teleclaude/spec/feature/workflow/todo-management`).
  Work the project delivered before it moved to the GitHub store stays in the
  frozen local store and is never on the board.
- **Lanes:** one lane per item, in this order: Icebox, Prepare, Work,
  Delivered. An iceboxed item is in Icebox and a delivered item in Delivered.
  An active item is in Prepare until its lifecycle phase reaches prepared, and
  in Work from then until it is delivered, following the prepare and work
  lanes of the lifecycle
  (`local/projects/teleclaude/spec/feature/workflow/todo-lifecycle-phase`).
  The lane is the board's Status field.
- **Needs you:** an open item carries the needs-you marker while the platform
  will not move it on its own and only a person can: while a human approval it
  waits on is outstanding, and while it is held or blocked and no session holds
  its claim. The marker clears in the same change that ends that condition. The marker is the
  board's Needs you field, and the board's Needs you view shows only the items
  carrying it.
- **Kept true:** a change to an item's phase, freeze, delivery, removal,
  hold, approval or claim sets its lane and marker on the board in the same
  write path that records it, under the platform App. The board never decides
  whether a workflow change succeeds: a board update that fails leaves the
  workflow change in place and is completed by the store's next refresh
  (`local/projects/teleclaude/design/architecture/workflow-store`).
- **Board automations:** automations of the board itself that would set a
  lane or remove an item are off, so the platform is the board's only writer.
- **Repair:** `telec todo board repair` rebuilds every item, lane and marker
  on the project's board from its GitHub store, restores the board's lanes,
  Needs you field and view, and turns off any board automation. A missed
  update or a hand edit on the board is corrected by it, never adopted. Its
  outcome names what it could not write and why, such as a missing App
  permission or a repository owned by a personal account, and while the board
  is not yet created it names the computer that creates it.

### Use cases

#### UC-WB1: See where all of a project's work stands

```gherkin
Scenario: The board shows each open item in its lane
  Given a GitHub-backed project in an organization's repository
  And the project has iceboxed items, items in preparation and items being built
  When the person running the project opens its board
  Then every iceboxed item is in the Icebox lane
  And every item still being prepared is in the Prepare lane
  And every prepared or building item is in the Work lane

Scenario: An item changes lanes as its work moves
  Given an item on the board in the Prepare lane
  When its preparation completes, and later its delivery is recorded
  Then the item moves to the Work lane and then to the Delivered lane
  And nobody moved it on the board

Scenario: A removed item leaves the board
  Given an item on the board
  When the item is removed
  Then it is no longer on the board
```

#### UC-WB2: Find the work that is waiting on me

```gherkin
Scenario: An item waiting on a person appears in the needs-you view
  Given an item on the board whose PRD awaits human approval
  When the person opens the board's needs-you view
  Then the item is shown there

Scenario: A held item nobody drives appears in the needs-you view
  Given an item that is held and that no session has claimed
  When the person opens the board's needs-you view
  Then the item is shown there

Scenario: An item leaves the needs-you view when it moves again
  Given an item shown in the needs-you view because it is held
  When its hold is released
  Then it is no longer shown in the needs-you view
```

#### UC-WB3: Restore the board after it went wrong

```gherkin
Scenario: The repair command undoes a hand edit
  Given someone moved an item to a different lane by hand on the board
  When an operator runs the repair command for the project
  Then the item is back in the lane its workflow record determines
  And the workflow itself did not change

Scenario: The repair command completes missed updates
  Given an item whose lane change did not reach the board
  When an operator runs the repair command for the project
  Then the item is in the lane and carries the marker its workflow record determines
```

## Known caveats

- A project whose repository belongs to a personal account has no board: the
  board is owned by an organization.
- The board shows an item's lane and whether it needs a person, not why; the
  reason is on the item's issue and in TeleClaude.
- A lane or marker update that fails reaches the board at the store's next
  refresh or a repair, so the board can lag the workflow record until then.
- A hand edit on the board stays visible until the item's next change or a
  repair, because the platform never reads the board back.
- Until the board is linked, it is listed among the organization's projects
  but not on the repository's Projects tab.
- The computer that takes on creating the board is the only one that ever
  creates it. If that computer leaves in the moment between taking it on and
  creating it, the board is created once a computer with that computer's name
  serves the project again.
