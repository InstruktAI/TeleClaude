---
description: A record the platform writes on a caller's behalf names the principal caller verification resolved for that caller, never an identity the invoking process read for itself.
delivered_by:
  - cli-authorization-reads-via-daemon
---

# Caller Attribution — Spec

## Required reads

- @docs/project/spec/identity-and-auth.md

## What it is

When a command records who made something — a content inbox entry's author, a
known-issue suppression's creation provenance, a sealed commit's author — the
name it records is the principal caller verification resolved for the invoking
caller: `human:<email>` for a registered person, whether a session carries that
principal or a terminal login names them, and the carried system principal for
work with no human origin. The invoking process sends its identity signals and
records the answer; it never reads a terminal login or a session identity
document to decide the name itself.

A caller that caller verification cannot identify has nothing recorded under a
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

- Attribution needs the platform's local service. When it is unreachable, a
  command that would attribute a record fails rather than recording a name the
  invoking process chose.
