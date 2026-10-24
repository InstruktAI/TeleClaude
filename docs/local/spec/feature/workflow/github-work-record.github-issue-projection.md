---
description: A project that selects the GitHub workflow store keeps its work items
  as issues in its own repository, where anyone can see at one glance where each
  item stands and what waits for a person, follow it from intent to delivered
  commit without TeleClaude, and where only the platform App's own writes count
  as the record.
---

# GitHub Work Record — Spec

## Required reads

- @docs/local/spec/domain/workflow.md

## What it is

A project that declares the GitHub workflow store keeps its repository work in
its own GitHub repository instead of the local todo database. The workflow runs
exactly as it does on the local backend: the same commands, phases, claims,
reviewers and stamps. What changes is where the record lives and who can read
it.

**Business value:** the people around a project follow its work where they
already are. Someone with access to the repository sees at one glance where
each work item stands and what waits for them, reads what was intended, how it
was prepared, reviewed and built, and which commit delivered it, without
knowing the platform, running TeleClaude or asking an agent. The record no
longer lives on one computer.

How the store maps onto the repository is owned by
`local/projects/teleclaude/design/architecture/workflow-store`.

## Canonical fields

- **Selection:** a project selects the store, names its repository and names
  the platform App that writes the record in its declaration
  (`local/projects/teleclaude/spec/teleclaude-config`). The App must be
  installed on the repository with issue write access; until it is, every
  workflow operation on the project refuses with that cause and nothing falls
  back to a local store.
- **Repository work only:** features, changes and bugs, and the group holders
  above them, are repository work. A task, and an item on the creative track,
  is not: it stays on the computer as it would on the local backend, never
  appears on GitHub, and an issue it already has is closed as not planned. An
  item that becomes repository work later appears on GitHub from then on, with
  its full history.
- **One issue per item:** each work item is an issue the platform App opened.
  Its title is the first meaningful heading of the item's current input, or
  the item's slug when the input has none. Its body is the item's current
  input without the generated `<slug> — Input` heading.
- **Kind:** the issue type is Feature, Change or Bug, following the item's
  kind. A group holder has no type.
- **Groups:** a group holder's members are its sub-issues. There is no group
  label.
- **Dependencies:** an item that depends on another open item on GitHub is
  blocked by that item's issue. A dependency on work that is not on GitHub is
  not shown.
- **Stage:** an item that is moving through the workflow carries exactly one
  `stage:` label for its lifecycle phase, from the table below. An item not
  yet started, a group holder and an iceboxed item carry none.
- **Status:** an item that stands still outside the work carries one
  `status:` label: `status:icebox` while it is iceboxed, `status:on-hold` while
  its dispatch hold is set. A held item keeps its stage label. The normal case
  carries no status label.
- **Waiting for a person:** the issue is assigned to the person the item's work
  runs for while its spec waits for their approval, and to the people an agent
  working on the item has just messaged
  (`local/projects/teleclaude/spec/messaging`). That message appears on the
  issue as a question comment carrying the link to the asking session. The
  assignment is removed when the item moves to another phase or the person
  answers in the asking session. A person is assigned only when their
  configuration declares their GitHub account
  (`local/projects/teleclaude/spec/teleclaude-config`).
- **Delivery and removal:** delivery closes the issue as completed. Removal
  closes it as not planned; reactivation reopens it.
- **Labels in the repository:** every label the platform sets exists in the
  repository with its colour and its one-sentence description below. No other
  label of the platform's exists there.

| Label                      | Lifecycle phase                         | Colour    | Description                                    |
| -------------------------- | --------------------------------------- | --------- | ---------------------------------------------- |
| `stage:prep.diagnosis`     | diagnose                                | `#d7af00` | The cause of this bug is being diagnosed.      |
| `stage:prep.spec`          | prd_drafting                            | `#d7af00` | The spec is being written.                     |
| `stage:prep.spec-review`   | prd_review                              | `#d7af00` | The spec is being reviewed.                    |
| `stage:prep.spec-approval` | prd_human_approval                      | `#d7af00` | The spec waits for a person's approval.        |
| `stage:prep.design`        | architecture_drafting                   | `#d7af00` | The technical design is being written.         |
| `stage:prep.design-review` | architecture_review                     | `#d7af00` | The technical design is being reviewed.        |
| `stage:prep.plan`          | plan_drafting                           | `#d7af00` | The implementation plan is being written.      |
| `stage:prep.plan-review`   | plan_review                             | `#d7af00` | The implementation plan is being reviewed.     |
| `stage:prep.blocked`       | blocked                                 | `#d7af00` | Preparation is stuck and needs a decision.     |
| `stage:prep.ready`         | prepared                                | `#5faf5f` | Prepared and ready to be built.                |
| `stage:work.build`         | build_started, review_changes_requested | `#d7af00` | Being built, or fixed after review.            |
| `stage:work.review`        | build_complete                          | `#d7af00` | The build is being reviewed.                   |
| `stage:integrate.queued`   | review_approved, finalize_ready         | `#5faf5f` | Approved and waiting to be merged.             |
| `status:icebox`            | (iceboxed)                              | `#5fafd7` | Parked in the icebox; not planned for now.     |
| `status:on-hold`           | (dispatch hold set)                     | `#d75f00` | Deliberately paused until someone releases it. |

- **Comments:** every comment the platform writes opens with one envelope line
  `[key:value ...]` that names only fields carrying information; the platform
  App as author is not repeated, and the machine data stays hidden below it.
  - The item's record: `[action:record phase:<phase> rev:<n>]`, adding
    `session:<id>` while a session holds the item's claim and `hold` while it
    is held, with the hold reason as one sentence under the envelope.
  - An artifact version: `[action:artifact name:<artifact> version:<n>]`,
    where `<n>` counts that artifact's versions on the item, followed by its
    content. Every version of every artifact (input, plan, findings, review
    reports, log and the rest) is appended in order and its content is never
    rewritten. A version too large for one comment continues in the next.
  - A question to a person: `[session:<id> role:<role> action:question]`,
    followed by the message and the link to the session.
  - A project ledger entry: `[action:ledger tx:<transaction>]`.
- **Project records:** commit reviews and documentation transfers, which
  belong to the project rather than one item, are appended to one
  platform-opened ledger issue.
- **Authority:** only what the platform App writes is the record. Labels,
  titles, bodies, types, relations, assignments, comments and edits by anyone
  else are visible on GitHub but never change the workflow, and the platform
  sets its own values again; a person steers the work through TeleClaude, not
  by editing the issue.

### Use cases

#### UC-GWR1: Follow a work item from intent to delivered commit

```gherkin
Scenario: A collaborator reads a delivered item on GitHub
  Given a project whose workflow store is GitHub
  And a work item was created, prepared, built, reviewed and delivered there
  When a collaborator with repository access opens the item's issue on GitHub
  Then they read the item's intent in the issue body
  And they read every artifact version in the order it was written
  And they see the stage changes as label events on the issue timeline
  And the closed issue names the commit that delivered the item

Scenario: An edit by someone else does not change the work
  Given a work item in progress on a GitHub-backed project
  When someone other than the platform App edits the issue body or changes its labels
  Then the workflow continues from the record the platform App wrote
```

#### UC-GWR2: See where the work stands and what waits for me

```gherkin
Scenario: The issue list shows each item's stage and kind
  Given a GitHub-backed project with items in preparation, in build and iceboxed
  When the person running the project opens the repository's issue list
  Then each moving item shows one stage label, and each iceboxed item shows the icebox label
  And each item shows its kind as its issue type

Scenario: An agent's question reaches the issue and the person
  Given an agent working on an item sends the person a message
  When the person opens the issue
  Then the issue is assigned to them
  And the message is on the issue with the link to the agent's session

Scenario: The assignment clears when the work moves on
  Given an issue assigned to the person because its item waits for them
  When the person answers in the session, or the item moves to its next phase
  Then the issue is no longer assigned to them
```

## Known caveats

- A project that selects the GitHub store by editing its declaration starts
  from what its repository holds. Its local store's open work moves only
  through the GitHub store switch
  (`local/projects/teleclaude/spec/feature/workflow/github-store-switch`).
- Work that is not repository work lives only on the computer that holds it,
  exactly as on the local backend.
- Removing an item past its retention window does not delete the issue: the
  platform App cannot delete issues, so the issue and its history remain,
  closed and marked purged.
- Two computers changing the same item at the same moment can lose one
  change; work on one item from one computer at a time.
- Writes take GitHub round trips, so workflow commands on a GitHub-backed
  project are slower than on the local backend.
- A workflow command whose reply from GitHub is lost reports a failure even
  when GitHub applied the change; the change appears once the store next
  refreshes from GitHub.
- An answer the person gives on the issue itself does not reach the session
  and does not clear the assignment.
- Labels, types, relations and assignments follow a change within the store's
  next refresh when the write that reflects them fails.
