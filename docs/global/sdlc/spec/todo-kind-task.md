---
description: 'Canonical definition of the `task` todo kind — the non-SDLC, side-effect-only work unit, and the boundary that keeps repo-touching work out of it.'
---

# Todo Kind: Task — Spec

## What it is

`task` is one of the four canonical todo kinds. It is the non-SDLC,
side-effect-only kind: a durable, human-authorized `task-plan` that performs
operations against the outside world. It never enters the SDLC — no PRD,
architecture, implementation-plan, or reviewer verdict — and is drafted by
`sdlc/procedure/lifecycle/task/prepare-task`, authorized by a human, and executed by `sdlc/procedure/lifecycle/task/run-task`.

## Canonical fields

- **Allowed** — telec CLI operations, external API/service calls, messaging
  and notification, research and data-gathering, and filesystem writes
  confined to the task's own workspace directory
  (`{project_root}/workspace/{slug}/`).
- **Disallowed** — any edit to a file tracked in the repository, and any
  commit. Work that requires either is `change`, `feature`, or `bug` — never
  `task`.
- **Discriminator** — does fulfilling the intent require touching the
  codebase? Yes → route to `change`/`feature`/`bug`. No, pure side effects →
  `task`. The filer applies this test when choosing the kind at creation, and
  task preparation applies it again
  (`sdlc/procedure/lifecycle/task/prepare-task`).

## Known caveats

- `sdlc/procedure/lifecycle/task/prepare-task` is the only remaining check before human authorization,
  and independently verifies this boundary before drafting a `task-plan`.
- `task` carries no exemption from the general minimal duplicate-check every
  todo creation owes (`sdlc/policy/todo-creation-discipline`).
  It does not, however, have a kind-specific home for **deep** landscape
  judgment — the yields/supersedes/dependency reconciliation `feature`,
  `bug`, and `change` each have at their own entry phase. That remains an
  open, separately-scoped gap; `sdlc/procedure/lifecycle/task/prepare-task` performs only the shallow
  scan, never the deeper reconciliation.
