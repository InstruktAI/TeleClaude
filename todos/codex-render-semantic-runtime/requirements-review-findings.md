# Requirements Review Findings: codex-render-semantic-runtime

## Critical

### 1. Scope still combines multiple independently shippable work streams

Grounded against the live code, the requirements currently bundle at least four
distinct streams of change:

- the core render-runtime refactor across `teleclaude/core/output_poller.py` and
  `teleclaude/core/polling_coordinator.py`
- low-risk fixes such as temp-dir teardown and capture-budget correction
- replay-corpus and instrumentation groundwork across tests/fixtures/docs
- the ephemeral control lane spanning delayed injection paths and the current key-only
  control surfaces in `teleclaude/core/command_handlers.py` and `teleclaude/api_server.py`

That is not one session-sized, atomic builder todo. Several pieces are independently
valuable and independently shippable, especially the teardown fix, capture-budget fix,
prerequisite replay/instrumentation work, and control-lane work. The current
requirements therefore fail the readiness size/coherence gate.

**Remediation:** Split the low-risk fixes, prerequisite evidence work, core
render-runtime refactor, and control-lane work into dependent todos. Keep the
render-runtime refactor as one coherent behavior, but do not bundle the prerequisite
and ancillary work into the same build todo.

### 2. Explicit pre-implementation unknowns are still not resolved, deferred, or dependency-tracked

`input.md` ends with five explicit unknowns: reconnect/startup authority boundaries,
real Codex replay corpus coverage, wake fidelity under lifecycle churn, control-lane
boundary identification, and tmux-call performance baseline. The requirements do not
say whether those unknowns are already resolved, have become prerequisite research, or
are being deferred.

That fails the "approach known" and completeness gates. The document currently assumes
builder-ready certainty while still depending on unanswered discovery work.

**Remediation:** For each unknown, either document the resolution, create a dependency/
spike todo, or defer it with justification. If replay corpus and performance baseline
remain open, they should be prerequisites rather than implicit builder discovery.

## Important

### 3. Requirement 9 is derived from open gaps, but it is not marked `[inferred]` or framed as prerequisite work

The requirements turn replay fixtures and performance instrumentation into an in-scope
deliverable. In `input.md`, those items appear as evidence gaps still needed before the
runtime refactor is safe, not as already-agreed product behavior. That blurs
human-stated intent with architect-inferred remediation.

This fails the inference-transparency rule and leaves a builder unclear on whether the
corpus/instrumentation work is feature scope, prerequisite evidence, or a separate
research track.

**Remediation:** Mark the derived requirement(s) `[inferred]` or move them into
prerequisite/dependency todos created from the unresolved unknowns.

## Suggestion

### 4. The performance success criterion is still too weak to act as a pass/fail gate

"Performance instrumentation can show a before/after reduction in tmux subprocess
churn or capture frequency for idle sessions" is directionally useful, but any tiny
reduction would satisfy it. That leaves too much room for a large refactor to pass
without materially changing idle behavior.

**Remediation:** Replace it with a concrete observable contract, such as an idle
capture ceiling, an audit-only cadence floor, or a session-level tmux-call budget.
