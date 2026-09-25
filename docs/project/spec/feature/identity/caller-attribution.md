---
description: A record the platform writes on a caller's behalf takes who made it from
  caller verification, never from an identity the invoking process read for itself.
---

# Caller Attribution — Spec

## Required reads

- @docs/project/spec/identity-and-auth.md

## What it is

When a command records who made something, it takes the answer from the platform's
resolution of its caller (`project/spec/identity-and-auth` §6): inside a session, the
session record its identity document names; outside any session, the person the
terminal's login names. It never takes a principal copied into the identity document,
and never a terminal login from inside a session. A content inbox entry's author and a
known-issue suppression's creation provenance name the resolved principal:
`human:<email>` for a registered person, whether a session carries that principal or a
terminal login names them, and the carried system principal for work with no human
<!-- planned-change:cli-actions-authorize-in-process -->
origin. A known-issue suppression and a sealed commit resolve their caller in the CLI
process; a content inbox entry takes its author from caller verification. A sealed
commit takes its author under the rules `project/spec/feature/agent_runtime/sealed-commit`
owns.
<!-- change:cli-actions-authorize-in-process -->
origin. A known-issue suppression, a sealed commit and a content inbox entry resolve their
caller in the CLI process. A sealed
commit takes its author under the rules `project/spec/feature/agent_runtime/sealed-commit`
owns.
<!-- /planned-change:cli-actions-authorize-in-process -->


<!-- planned-change:cli-actions-authorize-in-process -->
A caller that caller verification cannot identify has nothing recorded under a
<!-- change:cli-actions-authorize-in-process -->
A caller the platform cannot identify has nothing recorded under a
<!-- /planned-change:cli-actions-authorize-in-process -->
borrowed name: a command that would have to attribute a record to it refuses
instead, naming how to establish an identity. A name the operator states
explicitly for the record — a content author credited by `--author` — is authored
content, not attribution, and is recorded as given.

Each owning feature states its own attribution scenario: suppressions in
`project/spec/feature/workflow/known-issue-suppression`, sealed commits in
`project/spec/feature/agent_runtime/sealed-commit`. This spec carries the content inbox, which
has no other owning spec.

## Canonical fields

### Use cases

#### UC-CA-1: A content dump credits the resolved caller

```
Given an operator at a terminal whose login names a registered person, or an agent in a session carrying a principal
When they run telec content dump without --author
Then the created inbox entry's author is the principal the platform resolved for that caller
And the content-dumped notification carries the same author
```

#### UC-CA-2: A caller the platform cannot identify dumps nothing unattributed

```
Given a process the platform cannot identify
When it runs telec content dump without --author
Then no inbox entry is created
And the refusal names how to establish an identity
```

#### UC-CA-3: An explicitly credited author is recorded as given

```
Given an operator runs telec content dump with --author alice
When the inbox entry is created
Then its author is alice
And no identity lookup decides the author
```

### Cross-context references

- **workflow** — suppression provenance (`project/spec/feature/workflow/known-issue-suppression`).
- **agent_runtime** — sealed-commit author resolution (`project/spec/feature/agent_runtime/sealed-commit`).

## Known caveats

- Content inbox attribution needs the platform's local service. When it is
  unreachable, a content dump that would attribute its entry fails rather than
  recording a name the invoking process chose.

