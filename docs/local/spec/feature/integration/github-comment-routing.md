---
description: A configured person's comment or review on a GitHub-backed work item's
  issue or pull request reaches the session that holds the item's claim as that person's
  message, with its author and a link back; nobody else's does.
visibility: internal
---

# GitHub Comment Routing — Spec

## Required reads

- @docs/local/spec/feature/integration/github-webhook-normalization.md
- @docs/local/spec/feature/identity/human-identity-resolution.md

## What it is

A person who follows a work item on GitHub can talk to the work there, the
way they talk to a session on their own computer. What they write on the
item's issue or pull request reaches the session working the item as a message
from them; the work itself still changes only through that session and the
workflow it runs (`local/projects/teleclaude/spec/feature/workflow/github-work-record`).

**Business value:** a person reviewing a build on GitHub steers it from where
they are reading it, without opening TeleClaude and without an agent watching
GitHub for them.

## Canonical fields

- **What arrives.** A GitHub delivery relayed for a project
  (`local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`)
  that records a new issue or pull request comment, a submitted pull request
  review, or a new pull request review comment. Edits and deletions of any of
  them deliver nothing.
- **Whose words count.** Only a GitHub user — never a bot or App — whom GitHub
  reports as an owner, member or collaborator of the repository, and whose
  login resolves to a configured person
  (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`).
  Anything else delivers nothing and is logged without its text.
- **Where it goes.** The work item the issue or pull request belongs to, and
  the session holding that item's claim, are the GitHub store's answer
  (`local/projects/teleclaude/design/architecture/workflow-store`, work item
  lookup). The computer that hosts that session delivers it; every other
  computer that receives the same delivery does nothing. An item that belongs
  to no project here, or whose claim no live session holds, delivers nothing.
- **What the session receives.** One message from that person, delivered like
  any other message from them: their words, preceded by one line naming them,
  their GitHub login, what they did (commented, approved, requested changes,
  commented on a line) and the link to it on GitHub. A review submitted with
  no text still delivers that line.
- **Once.** A delivery GitHub repeats, or that several computers receive,
  reaches the session once.

### Use cases

#### UC-GCR1: A person steers a work item from GitHub

```gherkin
Scenario: A configured person comments on the pull request of an item in build
  Given a GitHub-backed project with an item whose build is under way
  And the person's configuration declares their GitHub account
  And they are a collaborator on the repository
  When they comment on the item's pull request on GitHub
  Then the session holding the item's claim receives their comment as a message from them
  And the message names them and links to the comment on GitHub

Scenario: A stranger's comment does not reach the work
  Given a public GitHub-backed project with an item in progress
  When someone who is not a configured collaborator comments on its issue
  Then no session receives the comment
```

## Known caveats

- Comments reach sessions only from repositories whose webhook delivers issue
  comments, pull request reviews and pull request review comments.
- A comment written while no session holds the item's claim is not delivered
  later; it stays on GitHub.
- Replies reach GitHub only through what the platform already writes there;
  this capability carries words from GitHub into the work and not back.
