# Requirements: prepare-state-machine

## Goal

Rewrite `next_prepare()` (core.py:2406-2577) from a linear if/else chain into a
deterministic state machine with durable checkpoints, modeled on the integration
state machine pattern (integration/state_machine.py).

Each call reads durable state from `state.yaml`, determines the current phase,
executes the next step, and returns structured instructions for the orchestrator.
The machine always returns tool-call instructions — never HITL guidance.

## In Scope

### R1: PreparePhase Enum

Define `PreparePhase(str, Enum)` with exactly these states:

- `INPUT_ASSESSMENT` — input.md exists, breakdown not assessed
- `TRIANGULATION` — deriving requirements from input.md via two-agent research
- `REQUIREMENTS_REVIEW` — requirements.md exists, awaiting review verdict
- `PLAN_DRAFTING` — requirements approved, implementation-plan.md needed
- `PLAN_REVIEW` — implementation-plan.md exists, awaiting review verdict
- `GATE` — both artifacts approved, running formal DOR validation
- `GROUNDING_CHECK` — gate passed, checking artifact freshness
- `RE_GROUNDING` — stale artifacts detected, updating against current truth
- `PREPARED` — terminal success state, todo ready for build
- `BLOCKED` — terminal failure state, requires human decision

Verification: Unit test confirms all 10 enum values exist and are string-typed.

### R2: State Machine Architecture

Replace the current `next_prepare()` implementation with a `_step()` dispatcher
following the integration state machine pattern (state_machine.py:603-702):

- Each phase has a dedicated `_step_<phase>()` handler
- Handlers return `tuple[bool, str]` — `(continue_loop, instruction)`
- A dispatch loop reads the checkpoint, calls `_step()`, and either loops or
  returns the instruction to the caller
- Loop limit prevents infinite cycling (use existing `_LOOP_LIMIT` pattern or
  a prepare-specific constant)

The function signature changes from:
```python
async def next_prepare(db: Db, slug: str | None, cwd: str, hitl: bool = True) -> str
```
to:
```python
async def next_prepare(db: Db, slug: str | None, cwd: str) -> str
```

The `hitl` parameter is removed entirely. The machine always returns `format_tool_call()`
instructions. Human interaction is via `next-refine-input` only.

Verification: Calling `next_prepare()` without `hitl` compiles and returns structured
tool-call instructions for every reachable phase.

### R3: Durable State in state.yaml

Extend state.yaml with these sections (persisted via existing `read_phase_state()`
/ `write_phase_state()` functions):

```yaml
grounding:
  valid: true|false
  base_sha: "<main HEAD when last grounded>"
  input_digest: "<hash of input.md>"
  referenced_paths:
    - "path/to/file.py"
  last_grounded_at: "<ISO8601>"
  invalidated_at: "<ISO8601 or null>"
  invalidation_reason: "files_changed|input_updated|policy_updated|null"

requirements_review:
  verdict: "approve|needs_work"
  reviewed_at: "<ISO8601>"
  findings_count: 0

plan_review:
  verdict: "approve|needs_work"
  reviewed_at: "<ISO8601>"
  findings_count: 0
```

The existing `dor` section in state.yaml remains unchanged. The new sections
extend the schema without breaking existing consumers.

Verification: Round-trip test — write extended state, read it back, all fields preserved.
Backward compatibility test — state.yaml without new sections loads with sensible defaults.

### R4: Phase Transitions

Implement deterministic transitions with the following rules:

| Current State | Condition | Next State | Event Emitted | Notes |
|---|---|---|---|---|
| (entry) | input.md exists, breakdown unassessed | INPUT_ASSESSMENT | — | [inferred] from current breakdown logic (core.py:2484-2506) |
| INPUT_ASSESSMENT | breakdown assessed | TRIANGULATION | — | [inferred] from current breakdown logic |
| (entry) | input.md exists, breakdown assessed, no requirements.md | TRIANGULATION | `prepare.triangulation_started` | |
| TRIANGULATION | requirements.md written | REQUIREMENTS_REVIEW | `prepare.requirements_drafted` | [inferred] event added — schema exists but input omits this edge |
| REQUIREMENTS_REVIEW | verdict == approve | PLAN_DRAFTING | `prepare.requirements_approved` | |
| REQUIREMENTS_REVIEW | verdict == needs_work | TRIANGULATION | — | |
| PLAN_DRAFTING | implementation-plan.md written | PLAN_REVIEW | `prepare.plan_drafted` | [inferred] event added — schema exists but input omits this edge |
| PLAN_REVIEW | verdict == approve | GATE | `prepare.plan_approved` | |
| PLAN_REVIEW | verdict == needs_work | PLAN_DRAFTING | — | |
| GATE | DOR score >= 8 | GROUNDING_CHECK | — | Single threshold, matches existing `DOR_READY_THRESHOLD` |
| GATE | DOR score < 8 | GATE (re-dispatch gate worker) | — | Gate worker re-assesses and updates score |
| GROUNDING_CHECK | fresh (digests match, no path changes) | PREPARED | `prepare.completed` | |
| GROUNDING_CHECK | stale | RE_GROUNDING | `prepare.grounding_invalidated` | |
| RE_GROUNDING | plan updated | PLAN_REVIEW | `prepare.regrounded` | |
| (any) | unresolvable blocker (missing input, superseded) | BLOCKED | `prepare.blocked` | |
| PREPARED | — | (terminal) | — | |
| BLOCKED | — | (terminal) | — | |

[inferred] The `needs_work` loop-back dispatches the producing worker with the
review findings attached, not a fresh dispatch. This enables targeted fixes.

[inferred] Entry-point logic (slug resolution, roadmap validation, container
detection) runs before the state machine dispatch loop, not as phases. These
are preconditions, not states — matching the integration pattern where slug
selection happens before `_dispatch_sync()`.

Verification: Unit test for each transition edge in the table. Each test sets
up the precondition state, calls the step handler, and verifies the resulting
phase and emitted event.

### R5: Event Emission

Emit lifecycle events at each phase transition using the fire-and-forget pattern
from integration (state_machine.py:533-545). All 10 prepare event types are
already registered in `software_development.py:194-300`.

Events include `slug` in the payload. Additional fields per event type:
- `prepare.grounding_invalidated`: include `reason` and `changed_paths`
- `prepare.blocked`: include `blocker` description

Verification: Mock EventProducer, trigger each transition, assert correct event
type and payload emitted.

### R6: Review Dispatch Commands

The state machine dispatches two review commands via `format_tool_call()`:

- **REQUIREMENTS_REVIEW** phase dispatches `next-review-requirements` with the slug
- **PLAN_REVIEW** phase dispatches `next-review-plan` with the slug

Each reviewer writes its verdict to state.yaml (`requirements_review.verdict` or
`plan_review.verdict`). On the next `telec todo prepare` call, the machine reads
the verdict and transitions accordingly.

[inferred] The review commands already exist as agent command specs. This
requirement covers only the dispatch from the state machine, not the review
command implementations themselves.

Verification: Unit test confirming REQUIREMENTS_REVIEW phase returns a tool-call
instruction with command `next-review-requirements`. Same for PLAN_REVIEW.

### R7: Grounding Check (Mechanical Freshness)

The GROUNDING_CHECK phase performs a deterministic, non-agent comparison:

1. Compare `grounding.base_sha` against current `git rev-parse HEAD`
2. Compare `grounding.input_digest` against current hash of `input.md`
3. Check if any path in `grounding.referenced_paths` was modified between
   `base_sha` and current HEAD (via `git diff --name-only`)

If all match: transition to PREPARED.
If any differ: transition to RE_GROUNDING with the diff.

Verification: Unit test with mocked git operations. Test fresh scenario (all match)
transitions to PREPARED. Test stale scenario (sha differs) transitions to RE_GROUNDING.

### R8: CLI Invalidation Check Flag

Add a new CLI mode to `telec todo prepare`:

```
telec todo prepare --invalidate-check --changed-paths foo.py,bar.py
```

Behavior:
- No slug argument — scans ALL active (non-icebox, non-delivered) todos
- For each todo with `grounding.referenced_paths`: check overlap with the
  provided changed-paths list
- If overlap found: set `grounding.valid = false`, `invalidated_at = now`,
  `invalidation_reason = "files_changed"` in state.yaml
- Emit `prepare.grounding_invalidated` event for each invalidated slug
- Pure mechanical operation — no agent dispatch, sub-second execution
- Returns JSON with list of invalidated slugs

This is designed for post-commit hooks or CI to invalidate stale preparations.

Verification: Unit test with a todo that has `referenced_paths: ["src/foo.py"]`.
Call with `--changed-paths src/foo.py`. Assert grounding.valid set to false.
Call with `--changed-paths unrelated.py`. Assert grounding.valid unchanged.

### R9: Pre-Build Freshness Gate

Before `next_work` dispatches a builder, it calls `next_prepare` as a pre-flight
check. If the state machine returns anything other than PREPARED, the build is
blocked until re-grounding completes.

[inferred] This integrates at the `next_work()` call site, not inside the
prepare state machine itself. The machine already handles staleness — the
pre-build gate simply calls it.

Verification: Integration test — set up a PREPARED todo, modify a referenced
file, call `next_work`. Assert it returns a re-grounding instruction instead
of a build dispatch.

### R10: Remove hitl Parameter

Remove the `hitl` parameter from:
- `next_prepare()` function signature
- CLI handler `handle_todo_prepare()` (remove `--no-hitl` flag parsing)
- API endpoint handler for `/todos/prepare`
- All callers of `next_prepare()`

The machine always returns `format_tool_call()` instructions. The `format_hitl_guidance()`
calls inside `next_prepare()` are replaced with `format_tool_call()` dispatches.

Verification: Grep for `hitl` in next_prepare-related code paths — zero occurrences.
All existing tests updated to not pass `hitl`.

## Out of Scope

- **Review command implementations** (`next-review-requirements`, `next-review-plan`):
  these are separate worker commands. This todo covers only the dispatch from the
  state machine.
- **Triangulation procedure implementation**: the two-agent triangulation is orchestrated
  by the `next-prepare` command, not by the state machine function. The machine emits
  `TRIANGULATION` as an instruction; the orchestrator executes it.
- **State machine for work phase** (`next_work`): separate concern. Only the pre-build
  freshness call-site integration (R9) touches `next_work`.
- **Agent command spec updates**: command markdown files are authored separately.

## Success Criteria

- [ ] `next_prepare()` is a deterministic state machine with durable checkpoints
- [ ] All 10 PreparePhase states are reachable and have handlers
- [ ] Every phase transition emits the correct lifecycle event
- [ ] Review loop-backs (needs_work) re-dispatch with findings
- [ ] Grounding check is mechanical (no agent, sub-second)
- [ ] CLI `--invalidate-check` flag works for post-commit automation
- [ ] Pre-build freshness gate prevents building on stale preparations
- [ ] `hitl` parameter fully removed from prepare code path
- [ ] All existing prepare tests updated for new architecture
- [ ] No regressions in existing todo prepare workflows

## Constraints

- Must follow the integration state machine pattern (checkpoint dataclass, step
  dispatcher, atomic I/O) for consistency across the codebase.
- State.yaml extension must be backward-compatible — existing state files without
  new sections must load with sensible defaults via `DEFAULT_STATE` merge.
- Event types must use the already-registered schemas in `software_development.py`.
  No new event registrations needed.
- The `db` parameter stays (needed for `compose_agent_guidance()` in tool-call
  formatting). Only `hitl` is removed.

## Risks

- **Test surface**: ~15 existing tests directly test `next_prepare()` behavior
  (test_next_machine_hitl.py, test_next_machine_breakdown.py). All must be
  rewritten for the new state machine architecture. Risk: high test churn.
- **Caller contract change**: removing `hitl` changes the function signature.
  All callers must be updated simultaneously. Risk: missed call sites.
- **Grounding check git operations**: `git diff --name-only` between SHAs
  requires the old SHA to still exist in the repo. Risk: force-pushed or
  shallow-cloned repos may not have the base SHA.
