---
description: "The artifact carrying a todo's human-approved intent, resolved by kind — prd for feature, input for change/bug."
visibility: 'public'
---

# Approved Intent Artifact — Concept

## What

The **approved intent artifact** is the single artifact that carries a todo's
authoritative intent — what the work must achieve. It is resolved by the todo's
`kind` and its creation contract:

| Todo                                          | Approved intent artifact                   | How it is produced                           |
| --------------------------------------------- | ------------------------------------------ | -------------------------------------------- |
| `feature`                                     | `prd`                                      | authored at intake, approved by the human    |
| `change`, `bug`                               | `input`                                    | the reporter's description or the bug report |
| `change` created with `--plan` and no `input` | the implementation plan's _Intent & scope_ | supplied at creation                         |

Each row is complete as stated. A `change` or `bug` carries no `prd`, and a
`--plan` change carries no `input`; neither absence is a gap. A worker grounding
in "the approved intent artifact" resolves it from this table, and an artifact's
mere presence — a legacy `requirements` artifact included — confers no intent
authority.

The artifact bounds the work's scope. A product outcome beyond what a `change`
or `bug` input authorizes enters the feature intent path rather than reaching
the plan.

## Why

`kind` is the routing authority, so intent resolves from `kind` as well. One
resolution rule lets every procedure name "the approved intent artifact"
instead of branching on artifact names, and keeps work whose kind carries no PRD
— or, on the `--plan` path, no input — first-class: a check that expects an
artifact the kind never produces blocks valid work on something that was never
meant to exist.
