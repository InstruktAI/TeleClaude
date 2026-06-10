---
description: 'The artifact carrying a todo''s human-approved intent, resolved by kind — prd for feature, input for change/bug.'
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

## Why

`kind` is authoritative for routing, and the intent artifact follows from it.
Before this concept, prepare/work procedures hard-coded `prd` and treated its
absence as a legacy defect — so a plan-only `change` or a `bug` (which never have
a PRD) drew a spurious "missing PRD" finding and burned a needless review round.
Naming one resolution rule — _intent = `prd` for feature, `input` for change/bug_
— lets every procedure reference it instead of branching on artifact names, and
keeps no-PRD work first-class.
