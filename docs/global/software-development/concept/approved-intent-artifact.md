---
description: "The artifact carrying a todo's human-approved intent, resolved by kind — prd for feature, input for change/bug."
visibility: 'public'
---

# Approved Intent Artifact — Concept

## What

The **approved intent artifact** is the single artifact that carries a todo's
authoritative, human-approved intent — what the work must achieve. It is resolved
by the todo's `kind`, not by which artifacts happen to exist:

| kind      | approved intent artifact | how it is produced                          |
| --------- | ------------------------ | ------------------------------------------- |
| `feature` | `prd`                    | authored at intake, human-approved          |
| `change`  | `input`                  | the reporter's description; no PRD authored |
| `bug`     | `input`                  | the bug report; no PRD authored             |

For `change` and `bug`, the absence of a `prd` is the **intended** design, not a
legacy gap — these kinds carry their intent in `input`. A worker that grounds in
"the approved intent artifact" reads `prd` when present and `input` otherwise, and
never treats a missing PRD on a `change`/`bug` as a defect.

A `change` created via `telec todo create --plan` is the one case where `input` is
also absent: the supplied `implementation-plan` is the intent basis, so the plan's
own _Intent & scope_ carries the approved intent and no `input` is authored. For a
`--plan` change the missing `input` is **intended** — never a defect or a blocker,
exactly as a missing `prd` is for any `change`/`bug`. The full resolution rule:
`prd` when present; otherwise `input` when present; otherwise, for a `--plan`
`change`, the `implementation-plan`'s _Intent & scope_. Resolution follows
artifact presence, never the transient `seeded` flag, which clears on the first
plan rewrite during plan-drafting.

## Why

`kind` is authoritative for routing, and the intent artifact follows from it.
Before this concept, prepare/work procedures hard-coded `prd` and treated its
absence as a legacy defect — so a plan-only `change` or a `bug` (which never have
a PRD) drew a spurious "missing PRD" finding and burned a needless review round.
Naming one resolution rule — _intent = `prd` for feature, `input` for change/bug_
— lets every procedure reference it instead of branching on artifact names, and
keeps no-PRD work first-class. The `--plan` create path extends the same logic one
step further: a seeded `change` has no `input` either, so a gate that asserts
`input` exists for every `change` would block `--plan` work on a missing artifact
that was never meant to exist. Resolving against the `implementation-plan` when
`input` is absent keeps no-input `--plan` work first-class too.
