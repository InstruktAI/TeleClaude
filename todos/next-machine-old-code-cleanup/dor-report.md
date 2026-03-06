# DOR Report: next-machine-old-code-cleanup

## Gate Verdict: PASS (score 8)

All eight DOR gates satisfied. Artifacts are well-structured, concrete, and grounded in
codebase evidence. No blockers.

---

### Scope Overlap Resolution

The original `input.md` described code + documentation changes. Codebase analysis confirms
`integration-event-chain-phase2` (DOR score 9, build pending) fully covers all code changes:

- **Lock removal** (phase 2 requirements #6): `acquire_finalize_lock`, `release_finalize_lock`,
  `get_finalize_lock_holder`, constants, `_finalize_lock_path`, session cleanup hook
- **`caller_session_id` removal** (phase 2 requirements #7): from `next_work()` signature and
  `/todos/work` API route
- **POST_COMPLETION rewrite** (phase 2 requirements #8): remove `telec todo integrate` and lock
  cleanup from `next-finalize` instructions

Phase 2's DOR report explicitly recommends: "Close or absorb the `next-machine-old-code-cleanup`
scaffolded todo after phase 2 delivers lock/caller_session_id removal."

**Resolution:** Rescoped to documentation-only cleanup. Phase 2 explicitly excludes
documentation updates ("Documentation updates — separate cleanup pass").

---

### Gate Results

#### 1. Intent & Success — PASS

Problem: four documentation files describe the old finalize lock / orchestrator-owned apply
model. After phase 2 removes the code, these docs become stale and misleading. Success
criteria are concrete: specific stale terms absent, specific new terms present.

#### 2. Scope & Size — PASS

Four documentation files, each independent. No code changes. Fits comfortably in a single
AI session.

#### 3. Verification — PASS

Demo scripts verify absence of stale terms (`finalize-lock`, `acquire_finalize_lock`,
`release_finalize_lock`, `get_finalize_lock_holder`, `orchestrator-owned apply`) and presence
of integrator references. `telec sync` validates doc structure.

#### 4. Approach Known — PASS

Documentation edits following established patterns. Each task specifies exact sections and
line numbers. The replacement content (integrator handoff model) is well-understood from
`integrator-wiring` delivery.

#### 5. Research Complete — PASS (auto-satisfied)

No third-party dependencies. All target files confirmed to exist. Stale content identified
and verified via codebase grep.

#### 6. Dependencies & Preconditions — PASS

Dependency on `integration-event-chain-phase2` is explicit in `roadmap.yaml`
(`after: [integration-event-chain-phase2]`). Phase 2 must deliver code changes before these
docs can be accurately updated.

#### 7. Integration Safety — PASS

Documentation-only changes. No code impact. Can be merged incrementally.

#### 8. Tooling Impact — N/A (auto-satisfied)

No tooling or scaffolding changes.

---

### Plan-to-Requirement Fidelity

Every implementation task traces to a requirement:

| Task | Requirement | File |
|------|-------------|------|
| 1.1 | finalize.md procedure describes integrator handoff | `finalize.md` |
| 1.2 | next-machine.md: no Finalize Lock section, integrator in dispatch table | `next-machine.md` |
| 1.3 | finalizer.md concept references integrator-owned merge | `finalizer.md` |
| 1.4 | session-lifecycle.md cleanup step omits finalize lock | `session-lifecycle.md` |
| 2.1 | No stale references remain; telec sync passes | all four files |
| 2.2 | Lint passes; all tasks checked | validation |

No contradictions. No tasks exceed requirement scope.

### Codebase Verification

All stale content confirmed present in target files:

- `next-machine.md`: Finalize Lock section (line ~162-170), invariant (line 66), failure modes (lines 210-211), lock references in mermaid diagram
- `finalize.md`: "orchestrator apply" in description and body; no integrator mention
- `finalizer.md`: "Finalize apply (orchestrator)" in step 3
- `session-lifecycle.md`: "Release finalize lock (if held)" in step 9 (line 146)

### Assumptions (inferred)

1. `integration-event-chain-phase2` will land as described (score 9, all gates pass).
2. The integrator model (queue + lease + singleton) replaces the finalize lock model.
3. Finalize Stage A (worker prepare in worktree) remains unchanged.

### Open Questions

None.

---

| Gate | Status |
|------|--------|
| Intent & Success | PASS |
| Scope & Size | PASS |
| Verification | PASS |
| Approach Known | PASS |
| Research Complete | PASS |
| Dependencies | PASS |
| Integration Safety | PASS |
| Tooling Impact | N/A |
| **Score** | **8** |
| **Verdict** | **pass** |
