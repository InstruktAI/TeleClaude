# Requirements Review Findings: codex-render-semantic-runtime

## Finding 1: Scope still bundles multiple independently shippable work streams

**Severity: Critical**

`requirements.md` keeps the core render-runtime refactor, temp-dir teardown, capture-budget
correction, replay/instrumentation groundwork, and control-lane work in one builder todo
([requirements.md](./requirements.md) lines 14-66). Grounded against the code, those map
to separate change areas:

- `teleclaude/core/output_poller.py` and `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/session_cleanup.py`
- `teleclaude/core/tmux_bridge.py`
- `teleclaude/core/command_handlers.py` and `teleclaude/api_server.py`
- tests/fixtures/docs called out in the requirements

That fails the readiness size/coherence gate. Several pieces are independently valuable
and independently shippable, especially the teardown fix, capture-budget fix, replay/
instrumentation groundwork, and control-lane work.

**Remediation:** Split the low-risk fixes, prerequisite evidence work, core render-runtime
refactor, and control-lane work into dependent todos. Keep the runtime refactor coherent,
but do not bundle prerequisite and ancillary work into the same build todo.

## Finding 2: Pre-implementation unknowns are still unresolved, undeferred, or not dependency-tracked

**Severity: Critical**

`input.md` explicitly says there are still things to learn before implementation
([input.md](./input.md) lines 125-139): reconnect/startup authority boundaries, real
Codex replay corpus coverage, wake fidelity under lifecycle churn, control-lane
boundary identification, and tmux-call performance baseline. The requirements do not
say whether those unknowns are resolved, deferred with justification, or moved into
prerequisite research/spike work.

That fails the "approach known" and completeness gates. The document reads as builder-ready
while still depending on unanswered discovery work.

**Remediation:** For each unknown, either document the resolution, create a prerequisite
todo/spike, or defer it explicitly with justification. If replay corpus and performance
baseline work remain open, they should be prerequisites rather than implicit builder
discovery during implementation.

## Finding 3: Replay-fixture and instrumentation work is inferred, but not marked `[inferred]`

**Severity: Important**

Requirement 9 and the related success criteria turn replay fixtures and performance
instrumentation into in-scope deliverables ([requirements.md](./requirements.md) lines
59-66 and 101-102). In `input.md`, those appear as evidence gaps and unanswered
questions, not clearly as human-stated feature requirements ([input.md](./input.md)
lines 80-84 and 130-139).

That fails the inference-transparency rule. A builder cannot tell whether replay corpus
and instrumentation work are agreed feature scope, prerequisite evidence work, or an
architect-inferred remediation path.

**Remediation:** Mark the derived requirement(s) `[inferred]` or move them into explicit
prerequisite/dependency todos created from the open unknowns.

## Finding 4: The performance success criterion is too weak to be a pass/fail gate

**Severity: Suggestion**

The current criterion says instrumentation should show "a before/after reduction in tmux
subprocess churn or capture frequency for idle sessions" ([requirements.md](./requirements.md)
lines 101-102). Any trivial reduction would satisfy that wording, which is too weak for
a refactor of this size.

**Remediation:** Replace it with a concrete observable contract, such as an idle capture
ceiling, an audit cadence floor, or a session-level tmux-call budget.
