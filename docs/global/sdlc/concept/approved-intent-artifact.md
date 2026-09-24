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

"the approved intent artifact" resolves by kind: `prd` for a feature and
`input` for a change or bug. It never grants authority from the accidental
presence of a legacy artifact, and it never treats a missing PRD on a change or
bug as a defect.

For a feature, the drafted PRD passes independent `prd_review` before the human
is asked to approve it. The review challenges the PRD's authorized horizon,
situation-specific enrichment, scope reasoning, assumptions, omissions, and
observable outcomes; it does not replace the human as intent authority.

For a change or bug, the `input` remains the approved intent authority. The
implementation plan's _Intent & scope_ makes the plan's interpretation and any
within-horizon shaping reviewable, and plan review applies the same preparation
quality contract. If shaping discovers a product outcome beyond the input's
authority, the work re-enters the feature intent path instead of acquiring
scope through the plan.

Legacy `requirements` artifacts remain readable as historical records but
carry no live intent fallback or creation semantics. Artifact presence never
overrides the kind-resolved authority above.

A `change` created via `telec todo create --plan` is the one case where `input` is
also absent: the supplied `implementation-plan` is the intent basis, so the plan's
own _Intent & scope_ carries the approved intent and no `input` is authored. For a
`--plan` change the missing `input` is **intended** — never a defect or a blocker,
exactly as a missing `prd` is for any `change`/`bug`. The full resolution rule:

`feature` resolves to `prd`; `change` and `bug` resolve to `input`; and the
explicit `--plan` change path resolves to the implementation plan's _Intent &
scope_ when no input was authored. The exceptional plan path is identified by
its creation contract, not by opportunistically selecting whichever legacy
artifact happens to exist.

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
