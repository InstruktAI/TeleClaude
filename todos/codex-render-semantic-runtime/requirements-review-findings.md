# Requirements Review Findings: codex-render-semantic-runtime

## Critical

### 1. Scope exceeds single-session capacity — splitting required

The requirements define 10 distinct in-scope deliverables spanning: new runtime actor
architecture, polling system rewrite, wake-signal infrastructure, control-lane
infrastructure, replay-fixture corpus, and documentation overhaul. This cannot fit a
single AI session without context exhaustion.

Several items are independently shippable and independently valuable:

- **Capture budget correction** (Req 6) — isolated constant split, no architectural
  dependency on the runtime refactor.
- **Teardown enrichment** (Req 7) — a one-function extension to `cleanup_session_resources`
  in `session_cleanup.py` to also remove `~/.teleclaude/tmp/sessions/{safe_id}/`.
- **Documentation realignment** (Req 10) — can ship before or after runtime changes.
- **Replay fixture corpus** (part of Req 9) — prerequisite infrastructure that enables
  safe refactoring of later items.

The core runtime refactor (Reqs 1–5) is one coherent behavior and should stay together,
but it is itself large enough to warrant its own focused todo.

The ephemeral control lane (Req 8) is architecturally independent of the render runtime
and should be a separate todo.

**Remediation:** Split into 4–5 dependent todos. The capture-budget fix and teardown
enrichment can be immediate low-risk deliverables. The replay corpus is a prerequisite
for the core runtime refactor. The control lane is independent.

### 2. Unresolved pre-implementation unknowns not dispositioned

`input.md` lines 125–139 list five explicit "What I still want to know before
implementation" items:

1. Reconnect/startup/headless-bootstrap authority table
2. Real-world replay corpus of Codex pane snapshots
3. Wake fidelity under lifecycle churn
4. Control-lane boundary identification
5. Per-session tmux subprocess performance baseline

The requirements do not address whether these are resolved, deferred, or require a
research spike. The DOR gate "Approach known — unknowns are small; if not, a research/
spike todo exists first" is not satisfied while these remain undispositioned.

**Remediation:** For each unknown, either (a) document the resolution in the requirements,
(b) create a research spike todo as a dependency, or (c) explicitly defer with
justification. Items 2 and 5 are natural prerequisites that become the replay-corpus
and instrumentation todos if splitting is adopted.

## Important

### 3. Missing config-surface awareness

Adaptive cadence (Req 4) will likely introduce new configuration keys (e.g., idle
cadence floor, active cadence ceiling, audit interval). Per the DoD checklist: "If new
configuration surface introduced (config keys, env vars, YAML sections): config wizard
updated, config.sample.yml updated, teleclaude-config spec updated."

The requirements do not mention config surface changes. A reviewer will flag this gap
at code review if not addressed now.

**Remediation:** Add a requirement or constraint acknowledging that new cadence
configuration, if introduced, must include config wizard exposure and sample config
updates.

### 4. No `[inferred]` markers on derived requirements

Several requirements expand beyond what `input.md` explicitly states:

- Req 2 formalizes the three-lane model with specific lane names and responsibilities
  beyond the input's bullet list.
- Req 9 frames the replay corpus as a deliverable requirement; the input frames it as
  a gap/desire.
- Req 10 frames documentation as a deliverable; the input frames it as a problem
  observation.

These inferences are reasonable and well-grounded, but per the quality standard:
"Anything inferred from codebase or documentation rather than explicitly stated in
`input.md` is marked `[inferred]`." Without markers, the human cannot distinguish
what they said from what the system assumed.

**Remediation:** Add `[inferred]` markers to expanded or derived items.

## Suggestion

### 5. Performance success criterion lacks threshold

Success criterion: "Performance instrumentation can show a before/after reduction in
tmux subprocess churn or capture frequency for idle sessions."

"A reduction" is not testable — any reduction, including 1%, satisfies it. Consider
specifying a meaningful threshold (e.g., "idle sessions capture at most once per
audit interval, not once per second") or framing it as an observable behavioral
change rather than a numeric comparison.

### 6. Implementation-adjacent language in constraints

Req 3 ("pipe-pane may be used as the wake signal") and Req 8 ("queued, non-durable
per-session control lane") prescribe specific mechanisms. These trace to agreed
architecture in `input.md` and function as solution-space constraints, so they are
acceptable — but a future reader might mistake them for implementation directives.
Consider prefixing with "Constraint:" or moving to the Constraints section.
