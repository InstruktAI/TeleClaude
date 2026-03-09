# DOR Report (Gate): codex-render-semantic-runtime

## Final Gate Verdict

- Status: `needs_work`
- Score: `7/10`
- Ready Decision: **Not Ready**

## Cross-Artifact Validation

### Plan-to-requirement fidelity: PASS

- Phase 1 covers the capture-budget correction, teardown cleanup, and hot-loop cost reduction.
- Phases 2 through 4 cover the render-aware runtime, explicit lane authority, wake-driven capture, and adaptive cadence.
- Phase 5 covers the ephemeral control-command lane without expanding the public key-only API.
- Phase 6 covers performance validation, docs/config realignment, and regression verification.
- No plan task contradicts the requirements. The plan preserves `agent_stop` as hook-authoritative and keeps rendered snapshots as the canonical live semantic source.

### Coverage completeness: PASS

- Every in-scope requirement has at least one plan task.
- Smaller scope items are still covered explicitly:
  - capture budget correction: Task 1.1
  - teardown tmp cleanup: Task 1.2
  - compound control queue: Tasks 5.1 and 5.2
  - performance proof and semantic parity: Tasks 6.1 through 6.4

### Verification chain: PASS (blocked by readiness gaps)

- Task-level verification is explicit throughout the plan.
- The plan closes with full lint/test/demo/integration checks, so the Definition of Done chain is present.
- The verification strategy is sufficient once the scope is split into buildable slices and the tmux integration research is recorded as durable documentation.

## DOR Gate Results

### 1. Intent & success: PASS

The problem statement, architectural direction, and desired outcomes are explicit in
`requirements.md`. Success criteria are concrete and testable: semantic parity for
Codex live events, reduced idle tmux overhead, startup/reconnect authority coverage,
config-surface synchronization, cleanup behavior, and documentation realignment.

### 2. Scope & size: FAIL

This is too broad for one builder session. The plan spans six phases, multiple new core
modules, fixture corpus creation, config-surface changes, documentation rewrites,
performance instrumentation, and full regression validation. It also combines at least
two independently shippable workstreams:

1. Core render-observability runtime refactor.
2. Ephemeral compound control queue.

Those can be reviewed and delivered separately without creating a half-working system.
Until the work is split into dependent todos and registered in `roadmap.yaml`, the item
does not satisfy the atomic-session gate.

### 3. Verification: PASS

Verification is well specified. The plan includes replay fixtures, parser invariants,
runtime lifecycle tests, config-surface checks, documentation updates, and final
`make test`, `make lint`, and demo validation. Error-path and lifecycle coverage are
called out explicitly for startup, reconnect, headless bootstrap, drift recovery, and
cleanup.

### 4. Approach known: PASS

The technical path is concrete. The artifacts identify the current code seams, define a
phased migration order, and use existing patterns already present in the codebase:
polling coordinator integration, tmux bridge helpers, config wiring, and runtime-owned
state. The remaining risk is execution breadth, not architectural ambiguity.

### 5. Research complete: FAIL

This change materially modifies a third-party integration surface: tmux
`capture-pane` and `pipe-pane` behavior become central to the runtime design. The input
captures useful local probe findings, but no indexed third-party research artifact was
found for tmux under the project or shared docs roots. The DOR policy requires that
such findings be captured as durable third-party documentation with authoritative
sources before dispatch.

### 6. Dependencies & preconditions: PASS (with follow-up)

External preconditions are otherwise clear:

- the tmux substrate stays in place,
- config-surface additions are explicitly listed,
- wizard/spec/sample updates are named,
- affected code paths are grounded.

The only missing precondition is the scope split required by Gate 2. That is
preparation work, not a human decision blocker.

### 7. Integration safety: PASS

The plan is explicitly incremental. It starts with low-risk corrections, builds a
semantic safety net before extraction, preserves adapter contracts and the tmux session
substrate, and keeps the key-only public API unchanged. The runtime and control work
can be staged without destabilizing main, provided the scope is split first.

### 8. Tooling impact: PASS

No scaffolding or build-tooling redesign is proposed. The only operator-facing surface
change is new polling configuration, and the plan already requires synchronized updates
to `config.sample.yml`, the wizard guidance, and the config spec.

## Review-Readiness Preview

- Test lane: strong. The plan is explicit about fixture-first safety nets, behavioral
  contract tests, and final integration checks.
- Security and operational review: acceptable. The work is internal, and cleanup,
  observability, lifecycle recovery, and failure handling are all called out.
- Documentation/config review: strong. Required updates to architecture docs, config
  docs, and wizard surfaces are already part of scope.
- Review-readiness gap: as one todo, the eventual diff would be too large and mixed to
  preserve TDD discipline and yield a clean review. Splitting is required before builder
  dispatch.

## Unresolved Blockers

1. Split this work into dependent builder todos so each item is atomic. At minimum,
   separate the core render-observability runtime from the compound control-queue lane,
   then register the resulting dependencies in `todos/roadmap.yaml`.
2. Capture the tmux `pipe-pane` and `capture-pane` behavior research as indexed
   third-party documentation with authoritative sources before dispatching the runtime
   refactor.

## Minimal Tightening Applied in Gate

1. Wrote the formal DOR verdict into `state.yaml`.
2. Created the missing `dor-report.md`.
3. Left `requirements.md` and `implementation-plan.md` unchanged because remediation
   requires broader prep work than a safe gate-time tightening.
