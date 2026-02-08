---
id: 'general/policy/checkpoint'
type: 'policy'
scope: 'global'
description: 'System-injected debrief at natural work breakpoints for knowledge capture, issue surfacing, and idea offloading.'
---

# Checkpoint — Policy

## Rules

- After each turn, the system injects a checkpoint message. It is not from the user.
- **Responding starts a new turn, which triggers another checkpoint.** If your work is done and you have nothing to report, do not respond. Silence breaks the cycle and is the correct answer.
- When a checkpoint arrives, debrief honestly:
  1. **Continue or done** — Is there more to do, or is the objective met?
  2. **Preserve** — Did you learn something worth keeping beyond this session?
  3. **Surface** — Did you encounter issues or work beyond this session's scope?
  4. **Offload** — Any friction, thoughts, or ideas worth offloading?
- **Quality over noise:** The debrief is not a form to fill out. If nothing genuinely needs surfacing, do not respond — go idle. A checkpoint that results in silence is a successful checkpoint; it means the system is clean. Only act if it would be valuable to your future self or a colleague picking up where you left off. Clutter degrades every tier it touches.
- **Trust and timing:** Do not debrief prematurely. If you are still in the middle of productive work, postpone — the debrief is always richer when all the learnings are fresh. Trust that the checkpoint will arrive at the right moment.
- The checkpoint is separate from the heartbeat. The heartbeat keeps you aligned mid-work. The checkpoint captures value when work pauses.

## Rationale

- Knowledge, bugs, and ideas are most accurately captured immediately after the work that produced them — not reconstructed from lossy memory at session end.
- A structured debrief at natural breakpoints ensures that nothing worth keeping is lost to context compression or session termination.
- Separating the debrief from the heartbeat keeps both mechanisms clean: the heartbeat is lightweight awareness; the checkpoint is deliberate reflection.

## Scope

- Applies to all agents during sustained or autonomous work sessions.
- The system delivers checkpoint messages; the agent's responsibility is to honor them.

## Enforcement

- Ignoring a checkpoint is a process violation — but honoring one does not require producing output. A brief mental pass through the four points with nothing to report is sufficient and expected.
- Premature debriefing (before work is complete) is discouraged — it interrupts flow and produces incomplete insights.

## Exceptions

- None. The checkpoint is lightweight by design.

## Tensions

- **Thoroughness vs. flow:** The debrief should be proportional to the work done. A small fix warrants a glance at the four points. A major feature warrants genuine reflection.
- **Completeness vs. noise:** Act only where it matters. A trivial entry in any tier adds clutter, not value.

> **Note to self:** The checkpoint is your debrief. Four questions, honest answers. Nothing to report? Pause — that's the right answer when the system is clean. Noise helps no one.
