# Plan Review Findings: prepare-pipeline-hardening

## Resolved During Review

### R1: Wrong event schema module path (grounding error)

**Severity:** Critical (resolved)

Task 8, Task 2 referenced files, state.yaml `referenced_paths`, and
demo.md all used `teleclaude_events/schemas/software_development.py`.
The actual path is `teleclaude/events/schemas/software_development.py`.

**Resolution:** Corrected all references in implementation-plan.md,
state.yaml, and demo.md.

---

## Critical

### C1: `--additional-context` CLI flag does not exist

Tasks 3b, 5, 11 and R17 all depend on `telec sessions run
--additional-context "..."`. This flag does not exist in the CLI module,
the command types, or the CLI surface spec.

The plan assumes this infrastructure exists but includes no task to create
it. R17 has no implementation path without it.

**Impact:** The entire `additional_context` mechanism — load-bearing for
R17 and used in 7 of the 9 re-dispatch scenarios — has no way to reach
workers.

**Remediation:** Either add a task to implement `--additional-context` in
the CLI (with corresponding CLI surface spec and help text updates), or
redesign the delivery mechanism to use an existing channel (e.g., a
temporary file the worker reads, or embedding context in the note that
`format_tool_call` already produces).

---

## Important

### I1: Shallow merge does not propagate nested v2 sub-keys

Task 1 asserts: "The default-merge in `read_phase_state()` already handles
missing keys, so existing todos get empty defaults transparently — no
migration step needed beyond the version bump."

The actual merge (core.py:980-981) is:
```python
merged = copy.deepcopy(DEFAULT_STATE)
merged.update(state)
```

This is a shallow dict update. Nested dicts from the persisted state
completely replace their DEFAULT_STATE counterparts. A v1
`requirements_review: {verdict: "approve", findings_count: 2, rounds: 1}`
will NOT have `findings: []` or `baseline_commit: ""` after merge — the
entire dict is overwritten by the v1 version.

**Impact:** Task 5 reads `findings` from the review dict. On v1 states,
this key won't exist, causing KeyError or requiring defensive `.get()`
everywhere. The "transparent migration" claim is wrong.

**Remediation:** Task 1 must either implement deep-merge for nested state
dicts (at minimum for `requirements_review`, `plan_review`, `grounding`,
and the new `artifacts`/`audit` dicts), or Task 5 and other consumers
must explicitly default missing sub-keys. The plan must be explicit about
which approach.

### I2: Demo/plan API naming mismatch

The demo calls `record_artifact_produced()` and
`record_artifact_consumed()`, but Task 2 defines `record_artifact_digest()`
with no `_produced`/`_consumed` variants. No `consumed` concept appears
in Task 2's helper API.

**Impact:** Demo will fail against the implemented API. The demo envisions
a richer lifecycle (produced/consumed distinction) that the plan doesn't
deliver.

**Remediation:** Either update the demo to match the plan's API
(`record_artifact_digest`), or update Task 2 to expose the richer API
the demo expects. The drafter must decide which API is correct.

### I3: `produced_at` write path not specified

Task 1 defines `produced_at` in the artifacts schema. Task 4 checks
`produced_at` for ghost artifact protection. But Task 2's
`record_artifact_digest()` only describes writing the `digest` field —
it does not mention writing `produced_at`.

No task assigns responsibility for writing `produced_at`, leaving ghost
artifact protection (R5) without its prerequisite data.

**Remediation:** Task 2 must explicitly state that `record_artifact_digest`
(or a renamed function) also writes `produced_at` and emits the
`artifact_produced` event with a timestamp.

### I4: `consumed_at` lifecycle gap

Task 1 defines `consumed_at` in the artifacts schema, but no task defines
who writes it or when. The staleness check (Task 2, Task 3) operates on
digest comparison, not consumption timestamps.

**Impact:** Either `consumed_at` is dead schema (unnecessary complexity),
or it's needed but missing implementation.

**Remediation:** If `consumed_at` is needed for the staleness cascade,
add a write path. If digest comparison is sufficient (as the plan implies),
remove `consumed_at` from the schema to avoid dead fields.

---

## Suggestions

### S1: Line number approximations are off by 15-20 lines

Task 4 says `~line 2948`, actual is 2967. Task 5 says `~line 3044`,
actual is 3063. Task 5 says `~line 3140`, actual is 3159. These are
navigational aids and don't affect correctness, but tighter approximations
help the builder.
