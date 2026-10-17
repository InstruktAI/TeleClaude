---
description: A record the platform writes on a caller's behalf takes who made it from
  caller verification, never from an identity the invoking process read for itself.
---

# Caller Attribution — Spec

## Required reads

- @docs/local/spec/identity-and-auth.md

## What it is

When a command records who made something, it takes the answer from the platform's
resolution of its caller (`local/projects/teleclaude/spec/identity-and-auth` §6): inside a session, the
session record its identity document names; outside any session, the person the
terminal's login names. It never takes a principal copied into the identity document,
and never a terminal login from inside a session. A content inbox entry's author and a
known-issue suppression's creation provenance name the resolved principal:
`human:<email>` for a registered person, whether a session carries that principal or a
terminal login names them, and the carried system principal for work with no human
origin. A known-issue suppression, a sealed commit and a content inbox entry resolve their
caller in the CLI process. A sealed
commit takes its author under the rules `local/projects/teleclaude/spec/feature/agent_runtime/sealed-commit`
owns.

A caller the platform cannot identify has nothing recorded under a
borrowed name: a command that would have to attribute a record to it refuses
instead, naming how to establish an identity. A name the operator states
explicitly for the record — a content author credited by `--author` — is authored
content, not attribution, and is recorded as given.

Each owning feature states its own attribution scenario: suppressions in
`local/projects/teleclaude/spec/feature/workflow/known-issue-suppression`, sealed commits in
`local/projects/teleclaude/spec/feature/agent_runtime/sealed-commit`. This spec carries the content inbox, which
has no other owning spec.

## Canonical fields

### Use cases

#### UC-CA-1: A person records content under their resolved identity

```gherkin
Scenario: Save content under the caller's identity
  Given a person or an agent acting for them has a verified platform identity
  When they save a content item without choosing an author name
  Then the item is attributed to the identity the platform resolved

Scenario: An unidentifiable caller cannot create unattributed content
  Given a caller cannot be identified by the platform
  When they save content without choosing an author name
  Then no content item is created
  And the caller is told how to establish an identity
```

#### UC-CA-2: A caller the platform cannot identify dumps nothing unattributed

#### UC-CA-3: An explicitly credited author is recorded as given

```gherkin
Scenario: Record a content item under an explicitly chosen author name
  Given an operator wants a content item credited to a chosen author
  When they save it with that author name
  Then the recorded author is exactly the name they supplied
  And caller identity does not replace it
```

#### UC-CA-4: A content dump lands in its project's inbox from anywhere inside it

```gherkin
Scenario: Save content into the working project's inbox
  Given an operator or agent is working in a project
  When they save a content item for that project
  Then it appears in the project's publications inbox
```

### Cross-context references

- **workflow** — suppression provenance (`local/projects/teleclaude/spec/feature/workflow/known-issue-suppression`).
- **agent_runtime** — sealed-commit author resolution (`local/projects/teleclaude/spec/feature/agent_runtime/sealed-commit`).

## Known caveats

- Content inbox attribution needs the platform's local service. When it is
  unreachable, a content dump that would attribute its entry fails rather than
  recording a name the invoking process chose.
