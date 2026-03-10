# DOR Report (Gate): codex-render-semantic-runtime

## Final Gate Verdict

- Status: `needs_work`
- Score: `7/10`
- Ready Decision: **Not Ready**

The artifact set is coherent and technically grounded, but it still fails two
Definition-of-Ready gates: atomic scope and third-party research capture.

## Cross-Artifact Validation

### Plan-to-requirement fidelity: PASS

- The requirements and plan agree on the core architecture:
  render-aware runtime, three observability lanes, wake-driven rendered capture,
  adaptive cadence, hook-authoritative `agent_stop`, teardown cleanup, and the
  non-durable control lane.
- No plan task contradicts a requirement. The plan keeps rendered snapshots as
  the canonical live semantic source and uses `pipe-pane` only as a wake signal.

### Coverage completeness: PASS

- Every in-scope requirement maps to at least one implementation task.
- Smaller but important requirements are explicitly covered:
  - capture-budget correction: Task 1.1
  - session tmp cleanup: Task 1.2
  - transcript/tmux fallback preservation: Tasks 6.2 and 6.4
  - control-lane scope limits: Tasks 5.1 and 5.2
  - performance proof and semantic parity: Tasks 2.2, 6.1, and 6.4

### Verification chain: PASS

- The plan defines observable proof for each phase: fixture corpus, parser replay,
  runtime lifecycle tests, config-surface synchronization, docs updates, and final
  integration checks.
- The verification chain is sufficient to satisfy the build/review quality gates
  once the readiness blockers below are resolved.

## DOR Gate Results

### 1. Intent & success: PASS

The artifacts state the problem, desired architecture, and measurable success
criteria clearly. The outcome is not "improve polling" in the abstract; it is a
specific runtime model with preserved Codex semantics, reduced idle tmux churn,
explicit lifecycle authority, cleanup behavior, and documentation/config alignment.

### 2. Scope & size: FAIL

This work is still too broad for a single builder todo.

Evidence:
- `implementation-plan.md` spans six phases and combines immediate fixes, replay
  corpus creation, semantic extraction, a new runtime actor, wake/cadence logic,
  a separate control queue, instrumentation, documentation rewrites, and full
  regression validation.
- `todos/roadmap.yaml` still contains only the single slug
  `codex-render-semantic-runtime` with no dependent child todos registered for the
  runtime lane and control-lane workstreams.

This fails the atomic-session gate. At minimum, split the core render/runtime work
from the ephemeral compound control queue and register the dependency order in
`todos/roadmap.yaml` before dispatch.

### 3. Verification: PASS

Verification is explicit and testable. The plan covers:
- replay fixtures and semantic parity checks,
- runtime and cleanup tests,
- config/documentation synchronization,
- startup, reconnect, headless-bootstrap, and drift-recovery coverage,
- final lint/test/demo validation.

The gate is blocked by readiness gaps, not missing verification.

### 4. Approach known: PASS

The technical path is concrete. The artifacts identify the relevant seams,
proposed modules, migration order, and invariants to preserve. This is an
execution-breadth problem, not an architecture-discovery problem.

### 5. Research complete: FAIL

The required third-party tmux research is still not captured as indexed durable docs.

Evidence:
- The design depends directly on tmux `capture-pane` and `pipe-pane` behavior.
- `docs/third-party/index.yaml` contains no tmux entry.
- `rg -n "tmux" docs/third-party/index.yaml docs/third-party -g '*.md'` returned no
  matches during this gate run.

`input.md` records useful local findings, but the DOR gate requires authoritative
third-party findings to be published into the third-party docs system before build.

### 6. Dependencies & preconditions: PASS (follow-up required)

The operational preconditions are otherwise identified: tmux remains the substrate,
adapter contracts stay stable, config surface changes are enumerated, and the
affected code paths are grounded. The remaining missing preconditions are the scope
split and tmux research artifact.

### 7. Integration safety: PASS

The plan is intentionally incremental: low-risk fixes first, then semantic safety
net, then extraction/runtime changes, then cadence/wake logic, then validation.
This can be merged safely in stages once the prep work is split into buildable units.

### 8. Tooling impact: PASS

No scaffolding or platform-tooling redesign is proposed. The only operator-facing
surface change is polling configuration, and the plan already requires synchronized
updates to the sample config, wizard guidance, and config spec.

## Review-Readiness Preview

- Test lane: ready once split. The plan is explicit about behavior-first checks and
  semantic replay.
- Security/operations lane: acceptable. Cleanup, observability, and lifecycle
  recovery are explicitly in scope.
- Documentation/config lane: ready. The plan already includes the required updates.
- Review-readiness gap: the eventual diff would still be too large and mixed to keep
  review quality high or preserve TDD discipline as one todo.

## Unresolved Blockers

1. Split this work into dependent builder todos and register them in
   `todos/roadmap.yaml`. Minimum split: core render/runtime refactor vs. ephemeral
   control-queue work.
2. Capture tmux `capture-pane` / `pipe-pane` behavior as indexed third-party docs
   under `docs/third-party/` and sync the third-party index before dispatch.

## Minimal Tightening Applied In Gate

1. Re-ran the DOR assessment against the current repo state.
2. Refreshed `state.yaml` with the current gate timestamp and unchanged verdict.
3. Rewrote this report with concrete repo evidence for the unresolved readiness gaps.
