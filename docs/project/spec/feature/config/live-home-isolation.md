---
description: Only delivered code changes the live configuration home. Code running from a todo's slug worktree may read it but is refused when it persists configuration there, and the refusal names a scratch home as the way to exercise that code.
visibility: internal
delivered_by:
  - config-worktree-write-guard
---

# Live Home Isolation — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The live configuration home is the machine user's default TeleClaude home. Every
delivered process on the machine reads its configuration from there, so a change
to it reaches all of them at once. Only code delivered to the canonical checkout
changes it.

Code running from a todo's slug worktree is undelivered. It reads the live home
like any other code, but when it persists configuration there the config context
refuses the write before the target changes, and the committed document stays
exactly as it was. The refusal names the document and the way to exercise that
code: start the process with its home set to a scratch home, where the same code
writes freely. The home is fixed when the interpreter starts, so a home set later
in the process redirects nothing.

Where the running code lives decides whether it is undelivered, not the directory
it was invoked from. Delivered code whose working directory is a slug worktree —
an agent hook firing for a worktree session, the installed CLI serving another
project's worktree — writes the live home as it always has. The integration
worktree is not a slug worktree.

The boundary is the configuration the config context persists under the live
home: the machine configuration, the global, person, and company configuration
documents, the environment and secret stores beside them, and the invitation
register. The other records kept under the home — session declarations,
checkpoint markers, logs, runtime settings state, and the project registry — are
outside it. Configuration files outside the home, including a worktree's own
project configuration, are outside it too.

## Canonical fields

- **Live home:** the default TeleClaude home of the machine's user. A home
  selected through `TELECLAUDE_HOME` that resolves to any other location is a
  scratch home; one that resolves to the default location is the live home.
- **Undelivered code:** code whose checkout is a todo's slug worktree.
- **Refusal:** an error naming the refused document and the scratch-home door,
  raised before the document changes. It is never reported as a storage failure.
- **Refusal record:** each refusal emits one production-level decision record
  naming the refused document and the running code's checkout.

### Use cases

#### UC-LHI-1: Undelivered code cannot change a live configuration document

```gherkin
Given an agent runs code from a todo's slug worktree
And the process's home is the live home
When that code persists a change to a configuration document in the live home
Then the operation fails with an error naming the document and a scratch home as the way to run it
And the live document is byte-for-byte unchanged
```

#### UC-LHI-2: A scratch home accepts writes from undelivered code

```gherkin
Given an agent starts code from a todo's slug worktree with its home set to a scratch home
When that code persists a change to a configuration document in that home
Then the change is committed in the scratch home
And no document in the live home changes
```

#### UC-LHI-3: Undelivered code still reads the live home

```gherkin
Given an agent runs code from a todo's slug worktree
And the live home's configuration documents need no rewrite to load
When that code loads configuration
Then it receives the same configuration delivered code receives
And no refusal occurs
```

#### UC-LHI-4: Delivered code writes the live home from any working directory

```gherkin
Given code from the canonical checkout runs with a todo's slug worktree as its working directory
When it persists a change to a configuration document in the live home
Then the change is committed
And no refusal occurs
```

## See Also

- ~/.teleclaude/docs/general/principle/trust-and-guardrails.md — why a write that other processes have already read from cannot be repaired by restoring the file, and why a refusal names its door.
- docs/project/policy/single-database.md — the same isolation for databases: worktrees never touch production state.
