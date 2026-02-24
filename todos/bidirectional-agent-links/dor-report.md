# DOR Report: bidirectional-agent-links

## Gate Assessment (Formal)

### Gate 1: Intent & Success — PASS

`input.md` and `requirements.md` clearly state the problem and expected outcome:
replace one-way relay behavior with a shared conversation-link primitive that preserves
existing worker notification behavior.

Success criteria are concrete (`SC-1` through `SC-10`) and testable. Each criterion
has explicit verification steps.

### Gate 2: Scope & Size — PASS (with observation)

10 tasks across ~11 files is substantial but well-sequenced into 5 phases:
foundations → lifecycle → routing → distributed + cleanup → gathering + tests.

Tasks are atomic and can be committed individually. A disciplined builder with
per-task commits should manage this within a single session.

### Gate 3: Verification — PASS

Verification path is explicit via:

- unit tests for listeners/coordinator/cleanup,
- a dedicated bidirectional-link test suite,
- runtime log checks for direct-link and cleanup behavior,
- `demo.md` captures observable checks and expected outcomes.

### Gate 4: Approach Known — NEEDS WORK

The approach is grounded in existing patterns (listener registration, agent_stop
framing, session cleanup hooks, Redis transport). No architectural unknown blocks
a first implementation pass.

**However**, the plan introduces a new link system to replace the existing
`session_relay.py` polling relay, but no task addresses the transition:

- `session_relay.py` (tmux pane polling at 1s intervals, in-memory state)
- `_start_direct_relay` in `handlers.py` (called on `direct=true`)
- Relay cleanup in `session_cleanup.py` (lines 70-79)
- `tests/unit/test_session_relay.py`

The plan says "instead of a separate relay path" but leaves the old path in place.
This creates risk of conflicting behavior (relay + link both active for the same
session pair) and orphan code.

### Gate 5: Research Complete — PASS (auto-satisfied)

No new third-party dependency or integration is introduced.

### Gate 6: Dependencies & Preconditions — PASS

- Slug is active and first in `todos/roadmap.yaml`.
- No external dependencies block implementation.
- All required subsystems exist (session listeners, hook events, send_message,
  cleanup hooks, Redis transport).

### Gate 7: Integration Safety — PASS

The requirement to preserve non-direct worker behavior is explicit (SC-9) and testable.
The plan includes regression coverage. Incremental merge is safe as long as the
relay conflict is resolved.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No tooling/scaffolding change is required by this todo.

### Plan-to-Requirement Fidelity — PASS (with one gap)

All 10 success criteria map cleanly to plan tasks:

| Requirement | Plan Task(s) |
| ----------- | ------------ |
| SC-1        | Task 1 + 3   |
| SC-2        | Task 1 + 9   |
| SC-3        | Task 3       |
| SC-4        | Task 5       |
| SC-5        | Task 6       |
| SC-6        | Task 6       |
| SC-7        | Task 4       |
| SC-8        | Task 8       |
| SC-9        | Task 2       |
| SC-10       | Task 7       |

No contradictions between plan tasks and requirements. The only gap is the
missing relay removal/migration task (approach, not fidelity).

## Assumptions

1. `requirements.md` is canonical for link sever semantics (SC-7: any member can
   sever), superseding `input.md`'s older asymmetric role model. Correct.
2. Link durability across daemon restart is not required in this phase as long as
   cleanup guarantees and runtime correctness hold.

## Gate Verdict

- **status**: `needs_work`
- **score**: `7/10`
- **assessed_at**: `2026-02-24T23:15:00Z`

### Blockers

1. **Missing relay-to-link transition task**: The plan must address the existing
   `session_relay.py` module and its integration points. Options:
   - Add a task to remove `session_relay.py`, `_start_direct_relay`, relay cleanup
     code, and relay tests — replacing them with the new link-based system.
   - Or explicitly document coexistence rules if both systems should remain.
     The plan currently introduces a replacement without removing the replaced system.

### Actions Required

- Add relay transition task to `implementation-plan.md` (either removal or coexistence policy).
- Once addressed, re-gate. Expected score: 8-9.
