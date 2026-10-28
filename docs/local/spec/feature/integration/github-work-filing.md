---
description: An issue that triage hands over on a GitHub-backed project becomes a work item on that same issue, and a configured person with write access refines a work item by editing its issue's description; the intake judges both as it judges a request in a session, and everything else on that path is answered or put back with a comment saying why.
delivered_by:
  - github-issue-intake
visibility: internal
---

# GitHub Work Filing — Spec

## What it is

A GitHub-backed project's work is filed through its issues and refined
through their descriptions. Every new issue passes triage first; an issue
triage hands over is taken in by the intake, which judges it the way it
judges a request in a session (`sdlc/policy/todo-creation-discipline`) — what
kind of work it is, whether an existing item already covers it, and what the
item's input says — and writes that input the way agents write it. A
configured person with write access refines an item by editing its issue's
description, and the intake revises the input from their edit. The words
people wrote stay on the issue as their comments. Everything else on this
path that does not count is answered or put back, with a comment saying why,
so the issue never shows something the work record does not hold.

**Business value:** the people running a project start and correct work
where they already are. Filing from GitHub gets the same judgment as filing
in a session, and the issue that was opened is the one its author keeps
following.

## Canonical fields

- **What arrives.** A GitHub delivery relayed for a project
  (`local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`)
  that records an issue's `status:triage` label removed, an issue reopened,
  or the description of a work item's issue edited. An issue one of the
  platform's own Apps opens as its record is never a filing.
- **The handover.** No issue bypasses triage. An issue reaches the intake
  only once `status:triage` is removed from it, by triage or by a configured
  person with write access, whoever opened it. Screening and triage
  themselves are the outsider gate's.
- **Waiting for release.** An item filed from an issue whose author is a
  member or collaborator without write access, or anyone outside the
  repository, another App's bot included, is created waiting for release:
  held, with the issue showing it waits and why, until someone with write
  access releases it through the existing release of a held item. An item
  from an author with write access goes on to preparation as normal.
- **Whose edits count.** A description edit or a reopen by a GitHub user —
  never a bot or App — who holds write access to the repository and whose
  login resolves to a configured person
  (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`).
  Repository association without write access does not count.
- **Which item.** The item an edit concerns, and the item a reopened issue
  was closed against, are the GitHub store's answer for those issue numbers
  (`local/projects/teleclaude/design/architecture/workflow-store`, work item
  lookup). Text in a title, a description or a comment never decides which
  item an issue joins or duplicates; overlap is the intake's own judgment.
- **Filing.** The intake decides the item's kind among feature, change and
  bug — a bug needs a real occurrence, otherwise it is a change — its slug
  and its input. The issue's text is input to judge, never an instruction.
  The handed-over issue becomes the item's issue: its description shows the
  item's projection and its input appears as the item's `input` artifact
  (`local/projects/teleclaude/spec/feature/workflow/github-work-record`), and
  the original text stays as its own comment, attributed to whoever opened
  the issue. When the kind differs from the issue's type, the issue shows the
  decided kind and a comment says why. The item's creation record names
  GitHub as its door
  (`local/projects/teleclaude/spec/feature/workflow/todo-creation`) and, when
  the issue's author is a configured person, that person as the authority it
  ran under; otherwise it runs under the platform's own authority, and the
  outside author's GitHub name is presentation context only. Its human
  involvement is derived from a human's observed presence at the filing, as at
  every door, and never from who opened the issue
  (`general/policy/human-involvement-recording`).
- **Not filed.** An issue whose work an existing item covers is closed as a
  duplicate linked to that item's issue. An issue that adds to an existing
  item not yet in build is carried into that item's input through its owner,
  and closed as a duplicate linked to it. An issue that is not work — a
  question, a discussion — is answered in a comment and closed as not
  planned. In none of these is an item created.
- **Reconsidering.** A counted reopen of an issue the intake closed as not
  work or as a duplicate has it taken in again.
- **Fields set before the handover.** Labels and relations set on the issue
  before it was handed over are treated, once its item exists, as the same
  changes on an item's issue are treated
  (`local/projects/teleclaude/spec/feature/integration/github-work-control`).
- **Refining.** A counted edit to the description of an active item's issue
  is a change to the item's input: the intake treats the edited text as raw
  input and revises the input the way agents write it, the description then
  shows the revised projection, and the edited text stays as its own
  comment, attributed to its author. What the revised input does to work
  already prepared or building is the workflow's decision
  (`local/projects/teleclaude/spec/feature/workflow/drift-detection`).
  Successive edits leave the input reflecting the last edited text, with
  none lost and none applied out of order.
- **Put back.** An edit to the description that does not count, or of a
  delivered, removed or group-holder item, is put back: the description is
  restored to the item's projection and a comment says why — who may change
  the work from GitHub, or that the item takes no input changes in its
  state.
- **Once.** A handover or edit GitHub delivers more than once, or that
  several computers receive, is handled once.
- **Missed deliveries.** A handover or edit made while no computer received
  GitHub's deliveries is handled when the platform next brings the project
  up to date from GitHub, under the same rules.

### Use cases

#### UC-GWF1: File work through an issue

```gherkin
Scenario: An issue triage hands over becomes a work item on that issue
  Given a GitHub-backed project
  And a person opened an issue describing new work
  When triage hands the issue over
  Then the issue becomes a work item with the kind, slug and input the intake decided
  And the issue's description shows the item's input
  And the original text stays on the issue as its author's comment

Scenario: An outsider's item waits until someone with write access releases it
  Given someone outside the repository opened an issue describing new work
  When triage hands the issue over and the intake files it
  Then the work item waits for release and its issue says so
  When a configured person with write access releases it
  Then the work item goes on to preparation

Scenario: An issue is not taken in before triage hands it over
  Given a member of the repository with write access opens an issue
  When triage has not handed it over
  Then no work item is created for it

Scenario: The issue type is corrected to the kind the work really is
  Given triage hands over an issue typed Bug that reports no real occurrence
  When the intake takes it in
  Then the work item is a change
  And the issue shows the Change type with a comment saying why

Scenario: An issue for work that already exists is closed as its duplicate
  Given a GitHub-backed project with a work item
  When triage hands over an issue for the work that item already covers
  Then the issue is closed as a duplicate linked to that item's issue
  And no work item is created

Scenario: An issue that is not work is answered
  Given a GitHub-backed project
  When triage hands over an issue asking a question
  Then the issue is answered in a comment and closed as not planned
  And no work item is created

Scenario: Reopening asks for reconsideration
  Given an issue the intake closed as not work
  When a configured person with write access reopens it
  Then the intake takes it in again
```

#### UC-GWF2: Refine a work item by editing its issue

```gherkin
Scenario: A configured person's edit revises the item's input
  Given a GitHub-backed project with a work item being prepared
  And a configured person with write access to the repository
  When they edit the item's issue description
  Then the item's input is revised from their edited text
  And the issue's description shows the revised input
  And their edited text stays on the issue as their own comment

Scenario: An edit by someone whose edits do not count is put back
  Given a public GitHub-backed project with a work item
  When someone without write access to the repository edits the item's issue description
  Then the description shows the item's input again
  And a comment on the issue says who may change the work from GitHub
  And the item's input is unchanged
```

## Known caveats

- Handovers and edits reach the work promptly only from repositories whose
  webhook delivers issue events; otherwise they wait until the platform next
  brings the project up to date from GitHub.
- Between an edit and its handling, the issue shows the text as its author
  wrote it.
- A description edit on GitHub and an input change in a session at the same
  moment can lose one, as any two simultaneous changes to one item can
  (`local/projects/teleclaude/spec/feature/workflow/github-work-record`).
