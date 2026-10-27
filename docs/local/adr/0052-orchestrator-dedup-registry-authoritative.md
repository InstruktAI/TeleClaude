---
visibility: 'internal'
number: '0052'
date: '2026-06-18'
description: 'Orchestrator dedup is registry-authoritative on the structured working_slug + orchestrator system_role fields; active_runner is demoted from sole dedup authority to the gate-approval/lane-handoff pointer and remains the dedup signal for non-orchestrator (task) drivers. Amends ADR-0035.'
---

# ADR-0052: Orchestrator Dedup Is Registry-Authoritative — ADR

## Context

ADR-0035 made the presence of a todo's `active_runner` link the entire
"already driven" signal: the lifecycle runner skips dispatch only when
`active_runner` names a live session, and `active_runner` is written solely by the
dispatcher (`dispatch_lifecycle_session` / `adopt_headless_session`). That decision
assumed there are no side spawn paths — every live driver is one the dispatcher
recorded.

That assumption is false for orchestrators. A `/prepare` (or `/work`)
session started directly through `telec sessions run` — by an operator, an agent,
or the TUI — flows through `POST /sessions/run`, which carries `working_slug` onto
the session row but never writes `active_runner` (only the dispatcher does). The
runner's dedup reads only `active_runner`, so such an orchestrator is invisible to
it, and the next event-driven pass dispatches a duplicate orchestrator for a slug
that already has a live one. WORK orchestrators happened to be identifiable by
their `trees/<slug>` worktree subdir; PREPARE orchestrators run on the repo root
and were not — the duplicate was observed in the prepare lane.

The session registry already holds the truth ADR-0035 chose to infer-by-link:
`working_slug` and `system_role` are persisted on every session row and are exact,
structured fields — not the fragile launch-time title/worktree heuristic ADR-0035
rightly rejected. `working_slug` was added after ADR-0035 (commit `f246fc004`), so
it did not exist when 0035 weighed its options.

## Decision

Orchestrator dedup is registry-authoritative. A slug is "already driven by an
orchestrator" when the session registry holds a live session with
`system_role == orchestrator` and `working_slug == slug` in the same canonical
project root. A single helper (`live_orchestrator_owner`, with a set-returning
sibling `live_orchestrator_owned_slugs` for the runner's full-set pass) is the
authoritative orchestrator dedup signal, consulted in both `decide_dispatches` and
the manual-start path.

`active_runner` is demoted from sole dedup authority. It remains:

- the gate-approval / lane-handoff pointer the workflow service dereferences; and
- the dedup signal for **non-orchestrator (task-lane) drivers** — a `/run-task`
  run session is not an orchestrator (`system_role != orchestrator`), so a
  registry query filtered on the orchestrator role would not catch it. The
  `active_runner` branch covers that case unchanged.

The short-lived dispatch claim keyed by `(project, slug, lane)` is retained for its
ADR-0035 job: bridging the boot gap between deciding to spawn and the spawned
session becoming registry-visible. The registry covers steady state; the claim
covers the gap. The caller's own session is exempt from the registry block so an
orchestrator adopting or continuing its own slug is not self-blocked.

## Consequences

- A live orchestrator bound to a slug blocks a second orchestrator regardless of
  how it was started (runner, operator/TUI, agent) or whether `active_runner` is
  set — the acceptance the duplicate-dispatch defect required.
- Dedup is exact-match on a structured field and scoped to the canonical project
  root, so one project's slug never blocks another project's same-named slug. This
  closes ADR-0035's prefix-collision objection without reintroducing the title
  heuristic it retired.
- Two dedup signals now coexist by design: the registry query for orchestrators and
  the `active_runner` link for task-lane drivers. The split is intentional, not
  redundant — each covers a driver class the other cannot see.
- `decide_dispatches` stays pure and synchronous: the single async registry read
  happens once in the runner caller, which passes the precomputed owned-slug set in.

## Alternatives Considered

- **Keep `active_runner` as the sole signal and write it on every spawn path.**
  Rejected: it would require every side spawn path (`telec sessions run`, TUI,
  agent) to write the dispatcher-owned link, reintroducing the multi-writer hazard
  ADR-0035 eliminated by making the dispatcher the sole writer. The registry already
  records ownership structurally; reading it is cheaper and has one writer (the
  session row).
- **Revive the title/worktree scan for prepare orchestrators.** Rejected for the
  exact reasons ADR-0035 retired it: launch-time titles and derived attributes are
  fragile. `working_slug` is the structured replacement that did not exist then.

## Status

Superseded in part by ADR-0078: time-bound dispatch claims are removed; the
registry-authoritative live-orchestrator decision remains accepted. Superseded
in part by ADR-0135: across computers, the claim judged by the computers that
could run its session decides whether a todo of a GitHub-backed project is
held.
