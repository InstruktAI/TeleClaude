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

<!-- planned-change:github-native-artifacts -->

- **Selection:** a project selects the store, names its repository and names
  the platform App that writes the record in its declaration
  (`local/projects/teleclaude/spec/teleclaude-config`). The App must be
  installed on the repository with issue write access; until it is, every
  workflow operation on the project refuses with that cause and nothing falls
  back to a local store.

<!-- change:github-native-artifacts -->

- **Selection:** a project selects the store, names its repository and names
  the platform App that writes the record in its declaration
  (`local/projects/teleclaude/spec/teleclaude-config`). The App must be
  installed on the repository with issue write access, and the repository must
  serve GitHub's issue artifacts, which GitHub offers as a preview to the
  organizations it enrolls; until both hold, every workflow operation on the
  project refuses with that cause and nothing falls back to a local store or to
  comments.

<!-- /planned-change:github-native-artifacts -->

- **Repository work only:** features, changes and bugs, and the group holders
  above them, are repository work. A task, and an item on the creative track,
  is not: it stays on the computer as it would on the local backend, never
  appears on GitHub, and an issue it already has is closed as not planned. An
  item that becomes repository work later appears on GitHub from then on, with
  its full history.

<!-- planned-change:github-item-acts -->

- **One issue per item:** each work item is an issue the platform App opened.
  Its title is the first meaningful heading of the item's current input, or
  the item's slug when the input has none. Its body is the item's current
  input without the generated `<slug> — Input` heading.

<!-- change:github-item-acts -->

- **One issue per item:** each work item is an issue the platform App opened.
  Its title is the title a person last gave it
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`),
  otherwise the first meaningful heading of the item's current input, or the
  item's slug when the input has none. Its body is the item's current input
  without the generated `<slug> — Input` heading.

<!-- /planned-change:github-item-acts -->

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

- **Board:** in a repository an organization owns, the project's work also
  appears on one board the platform keeps
  (`local/projects/teleclaude/spec/feature/workflow/workflow-board`).

- **Pull request:** from the moment an item's build starts until it is
  delivered or removed, its branch has one draft pull request, linked to its
  issue by its opening envelope `[action:pull-request issue:<n>]` and opened
  by the App mapped to the builder role
  (`local/projects/teleclaude/spec/teleclaude-config`). Each build review
  appears on it as a review by the App mapped to the reviewer role, on the
  commit that was reviewed: the verdict as approval or requested changes, the
  review findings as its body under the envelope
  `[session:<id> role:reviewer action:review round:<n>]`. Delivery closes it
  with `[action:delivered commit:<sha>]`; removal closes it. The platform
  merges on its own machine, never on GitHub.

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

<!-- planned-change:github-item-acts -->

- **Comments:** every comment the platform writes opens with one envelope line
  `[key:value ...]` that names only fields carrying information; the platform
  App as author is not repeated, and the machine data stays hidden below it.
  - The item's record: `[action:record phase:<phase> rev:<n>]`, adding
    `session:<id>` while a session holds the item's claim, `hold` while it
    is held, and `commit:<sha>` once it is delivered, with the hold reason as
    one sentence under the envelope.
  - A question to a person: `[session:<id> role:<role> action:question]`,
    followed by the message and the link to the session.
  - A project ledger entry: `[action:ledger tx:<transaction>]`.

<!-- change:github-item-acts -->

- **Comments:** every comment the platform writes opens with one envelope line
  `[key:value ...]` that names only fields carrying information; the platform
  App as author is not repeated, and the machine data stays hidden below it.
  - The item's record: `[action:record phase:<phase> rev:<n>]`, adding
    `session:<id>` while a session holds the item's claim, `hold` while it
    is held, and `commit:<sha>` once it is delivered, with the hold reason as
    one sentence under the envelope.
  - A question to a person: `[session:<id> role:<role> action:question]`,
    followed by the message and the link to the session.
  - A project ledger entry: `[action:ledger tx:<transaction>]`.
  - A change put back: `[action:put-back field:<field> change:<id>]`, where
    `<id>` names the change in the issue's history, followed by the change it
    puts back and why it did not count.

<!-- /planned-change:github-item-acts -->

<!-- planned-change:github-native-artifacts -->

- **Artifact versions:** every version of every artifact (input, plan,
  findings, review reports, log and the rest) is a platform comment opening
  with `[action:artifact name:<artifact> version:<n>]`, where `<n>` counts that
  artifact's versions on the item, followed by its content. Versions are
  appended in order and their content is never rewritten. A version too large
  for one comment continues in the next.

<!-- change:github-native-artifacts -->

- **Artifacts:** each artifact of an item (input, plan, findings, review
  reports, log and the rest) is one GitHub issue artifact on the item's issue,
  under the artifact's name, created by the platform App. Every version the
  workflow writes is a saved version of that artifact, in the order it was
  written, and is never rewritten. GitHub's history of the artifact names the
  platform App as the account that saved each version; which workflow session
  wrote a version, and when, is kept in the record for every version GitHub
  still serves. Implementation and task plans are plan artifacts, every other
  artifact a document. Workflow state too large for the record is kept the
  same way, as the item's `workflow-state` artifact. The platform writes no artifact content into a comment and reads none from one; content comments left from before native artifacts are no part of the record. A version someone else saves stays the artifact's current version on GitHub until the platform next saves that artifact, and is never part of the record; an artifact someone else adds is left as it is and is never part of the record.

<!-- /planned-change:github-native-artifacts -->

- **Project records:** commit reviews and documentation transfers, which
  belong to the project rather than one item, are appended to one
  platform-opened ledger issue.

- **Board issue:** where the project has a board, one platform-opened issue,
  closed as not planned, records which computer sets the board up and which
  board it is, as `[action:board-claim computer:<name>]` and
  `[action:board project:<number>]` comments.

<!-- planned:github-turn-mirror -->

- **Conversation:** every session the workflow starts for a repository work
  item has its conversation on that item: a turn completed while the item had
  an open pull request on that pull request, every other turn on its issue.
  Each completed turn is one comment, written
  by the App mapped to the session's role
  (`local/projects/teleclaude/spec/teleclaude-config`): the reviewer App for a
  review role, the author App for every other role, never the App that writes
  the record. It opens with
  `[session:<id> role:<role> action:turn turn:<n> at:<time>]`, where `<n>`
  counts that session's turns and `<time>` is when it completed, followed by
  the input the turn
  received and the agent's reply, without tool activity or reasoning. A
  person's comment that reached the session from GitHub is written like any
  other input; a message a person gave the session anywhere else is not
  written, and the turn notes only that the person spoke. Turns appear in the
  order they completed across all of the item's sessions, each exactly once,
  except that a turn one computer still owed when the item's work moved to
  another computer appears when it is posted, after later turns. A turn too
  large for one comment continues in the next. Before a turn is
  written, every secret the platform holds is masked, and credential-like
  strings and personal data are removed as far as detection recognizes them;
  a turn whose masking or detection cannot complete appears only as
  `[session:<id> role:<role> action:turn turn:<n> at:<time> withheld]`, with
  no content. The project's
  conversation starts at the moment recorded by the first
  `[action:conversation-start at:<time>]` entry on its ledger issue; turns
  completed before it are not written. The conversation is never part of the
  record, and writing it never holds up a session.

<!-- /planned:github-turn-mirror -->

<!-- planned-change:github-item-acts -->

- **Authority:** only what the platform's Apps write is the record. Labels,
  titles, bodies, types, relations, assignments, reviews, merges, comments and
  edits by anyone else are visible on GitHub but never change the workflow, and
  the platform sets its own values again. A configured collaborator's comment
  or review reaches the session working the item as their message
  (`local/projects/teleclaude/spec/feature/integration/github-comment-routing`);
  the work changes only through that session.

<!-- change:github-item-acts -->

- **Authority:** only what the platform's Apps write is the record. A change
  by a configured person with write access to the repository to an item's
  title, open state, platform labels, issue type, sub-issues or blocked-by
  relations is taken as the workflow act it stands for, and any other change
  to those fields is put back with a comment saying why
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`).
  Bodies, assignments, reviews, merges, comments and edits by anyone else are
  visible on GitHub but never change the workflow, and the platform sets its
  own values again. A configured collaborator's comment or review reaches the
  session working the item as their message
  (`local/projects/teleclaude/spec/feature/integration/github-comment-routing`).

<!-- /planned-change:github-item-acts -->

### Use cases

#### UC-GWR1: Follow a work item from intent to delivered commit

<!-- planned-change:github-item-acts -->

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

<!-- change:github-item-acts -->

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
  When someone whose changes do not count edits the issue body or changes its labels
  Then the workflow continues from the record the platform App wrote
```

<!-- /planned-change:github-item-acts -->

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

#### UC-GWR3: Follow a build on its pull request

```gherkin
Scenario: A collaborator follows a build and its reviews on GitHub
  Given a GitHub-backed project whose item has started its build
  When a collaborator opens the item's pull request on GitHub
  Then they see the build's commits as they are published
  And each review the platform's reviewer made, on the commit it reviewed, with its verdict and findings
  And the pull request closes naming the delivered commit when the item is delivered
```

<!-- planned:github-turn-mirror -->

#### UC-GWR4: Follow the agents' conversation on a work item

```gherkin
Scenario: A collaborator reads how the agents worked an item
  Given a GitHub-backed project with an item the workflow is preparing or building
  When a collaborator opens the item's issue, or its pull request once the build has started
  Then they read every turn of the item's sessions in the order the turns completed
  And each turn names its session and role, what the session was asked and what it answered
  And each turn is written by the identity of the session's role, not by the record's

Scenario: A turn that cannot be cleaned is withheld
  Given a session working an item completes a turn whose secrets or personal data cannot be removed
  When the turn appears on the item
  Then it shows that the turn was withheld, without any of its content
```

<!-- /planned:github-turn-mirror -->

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

- An answer the person gives on GitHub reaches the session holding the item's
  claim, not necessarily the session that asked; when another session asked,
  the issue stays assigned until the item moves to its next phase.
- Labels, types, relations, assignments, the pull request and its reviews
  follow a change within the store's next refresh when the write that reflects
  them fails.

<!-- planned:github-native-artifacts -->

- The record depends on GitHub's issue-artifacts preview. If GitHub changes or
  withdraws it, workflow writes on the project refuse, and the artifacts on
  GitHub may stop being readable.
- GitHub serves only the newest 30 versions of an artifact to the platform. A
  computer that rebuilds the work from GitHub restores at most those; older
  versions stay on the computer that wrote them.
- GitHub announces no change to an artifact and the platform does not scan
  for one, so a version someone else saves stays the artifact's current version
  on GitHub until the platform next saves that artifact; it never changes the
  work.
- A version larger than GitHub accepts for one artifact is refused, and the
  workflow command that wrote it fails with that cause.
- Work already on GitHub when native artifacts arrive is republished as
  native artifacts by the computer that works the project, a few items at a
  time within GitHub's limits; for a large repository this takes hours. A
  workflow command that changes an item not yet republished fails, saying to
  send it again, until that item is republished. On the computer that works
  the project, such a command moves the item to the front, so it is
  republished after the item in progress, or later when GitHub throttles the
  republication.

<!-- /planned:github-native-artifacts -->

<!-- planned:github-turn-mirror -->

- Credential-like strings and personal data are removed from a session's
  conversation only as far as detection recognizes them: what it misses is
  published with the turn. Secrets the platform holds are always masked.
- A session's turn appears on GitHub after it completes, and later than that
  while GitHub is unreachable or its request budget is spent. A turn that a
  computer could not post before the item's work moved to another computer
  appears after the turns completed after it, showing when it completed.

<!-- /planned:github-turn-mirror -->
