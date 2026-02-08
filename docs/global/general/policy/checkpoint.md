---
id: 'general/policy/checkpoint'
type: 'policy'
scope: 'global'
description: 'System-injected checkpoint at natural work breakpoints triggering validation and knowledge capture.'
---

# Checkpoint — Policy

## Rules

- After each turn, the system injects a checkpoint message. It is not from the user.
- **Responding starts a new turn, which triggers another checkpoint.** If everything is clean and there is nothing to act on, do not respond. Silence breaks the cycle and is the correct answer.
- The checkpoint is a trigger to **act**, not to report. Work through two phases:
  1. **Validate** (if you performed any work this turn) — Is it actually working? Check logs, run tests, verify services, finish loose ends. Fix anything broken before moving on.
  2. **Capture** (always) — Bugs, work items, lessons, ideas — route each to its proper destination.
- **Quality over noise:** If nothing genuinely needs validating or capturing, do not respond — go idle. A checkpoint that results in silence is a successful checkpoint; it means the system is clean. Clutter degrades every tier it touches.
- **Trust and timing:** Do not checkpoint prematurely. If you are still in the middle of productive work, postpone — the checkpoint is always richer when all the work is done. Trust that it will arrive at the right moment.
- The checkpoint is separate from the heartbeat. The heartbeat keeps you aligned mid-work. The checkpoint validates and captures when work pauses.

## Rationale

- Unverified work is not done work. The first instinct at a checkpoint must be to confirm that what was built actually holds up.
- Knowledge, bugs, and ideas are most accurately captured immediately after the work that produced them — not reconstructed from lossy memory at session end.
- Separating the checkpoint from the heartbeat keeps both mechanisms clean: the heartbeat is lightweight awareness; the checkpoint is deliberate action and capture.

## Scope

- Applies to all agents during sustained or autonomous work sessions.
- The system delivers checkpoint messages; the agent's responsibility is to honor them.

## Enforcement

- Ignoring a checkpoint is a process violation — but honoring one does not require producing output. A pass through both phases with nothing to act on is sufficient and expected.
- Validate first, capture second. If either phase produces work, do it. Only go idle when everything is clean.

## Exceptions

- None. The checkpoint is lightweight by design.

## Tensions

- **Thoroughness vs. flow:** Validation should be proportional to the work done. A small fix warrants a quick log check. A major feature warrants full verification.
- **Completeness vs. noise:** Act only where it matters. A trivial entry in any capture target adds clutter, not value.
