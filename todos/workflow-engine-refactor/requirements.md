# Requirements: workflow-engine-refactor

## Goal

Replace the bespoke prepare and work state machines with a single configurable
workflow engine. Same functionality, new architecture. Pure refactoring — no
new behavior.

The repeating pattern — produce artifact, review, iterate, approve — is
currently implemented as hand-coded phase handlers. The refactor should
represent that pattern through reusable workflow configuration instead of
duplicating lifecycle control flow.

## Scope

### In scope

1. **Workflow engine**: a reusable engine interprets workflow definitions and
   emits fully specified dispatch instructions.

2. **Workflow definitions**: declarative definitions describe the existing
   prepare and work lifecycles.

3. **Step metadata**: each workflow step carries enough information to dispatch
   producer/reviewer work, determine prerequisites and expected artifacts, and
   advance lifecycle state without bespoke phase code.

4. **Reusable validation**: workflow steps can request validation beyond the
   default artifact-existence checks.

5. **Language-aware code steps**: code-producing steps can augment their
   baseline context and verification expectations with the correct
   language-specific conventions for the target project.

6. **Consolidated workflow dispatch surface**: prepare/work lifecycle
   operations resolve through one workflow-oriented dispatch surface while
   preserving compatibility with current dispatch entry points during
   transition.

7. **[inferred] CLI integration**: the existing user-facing prepare/work entry
   points continue to start these flows through the same CLI surface; the
   refactor swaps internals without changing how operators invoke them.

8. **State compatibility**: existing todo state continues without manual
   migration.

9. **Event continuity**: existing lifecycle events continue to be emitted at
   the same transition points with the same payload semantics.

10. **[inferred] Orchestrator contract preservation**: the orchestrator-facing
    dispatch handoff remains compatible with the current dumb-relay contract.

11. **Migration**: the refactor replaces the current bespoke prepare/work
    lifecycle routing, including the existing review/fix loops and gating
    behavior.

### Out of scope

- Adding TDD/test-spec behavior (separate todo).
- Changing what workers do (same required reads, same artifacts, same procedures).
- Changing orchestrator role (still dumb relay).
- Changing state.yaml semantics (same fields, same values).
- Adding new workflow types (e.g. creative.yaml) — the engine supports them but
  this refactor only migrates existing prepare and work workflows.

## Success Criteria

- [ ] [inferred] `telec todo prepare <slug>` produces behaviorally equivalent
      dispatch instructions for all reachable prepare states before and after
      the refactor.
- [ ] [inferred] `telec todo work <slug>` produces behaviorally equivalent
      dispatch instructions for all reachable work states before and after the
      refactor.
- [ ] Workflow definitions for prepare and work are valid and represent the
      same step progression as the current prepare/work lifecycles.
- [ ] Reusable validation produces the same pass/fail outcomes as the current
      lifecycle validation.
- [ ] Existing todo state continues without manual migration.
- [ ] The consolidated workflow dispatch surface resolves each supported
      lifecycle operation to the correct workflow step and dispatch behavior.
- [ ] Existing dispatch entry points remain compatible during transition.
- [ ] Code-producing steps apply the correct language-specific conventions for
      the target project.
- [ ] All existing lifecycle events are emitted at the same transition points
      with the same payload semantics.
- [ ] [inferred] The orchestrator-facing dispatch instruction structure remains
      compatible with current orchestrator expectations.
- [ ] [inferred] Pre-commit hooks pass (tests, linting, type checking).
- [ ] [inferred] No regressions in existing prepare/work flows are caught by
      the relevant targeted tests and hook-validated checks.

## Constraints

- **Behavioral equivalence**: this is a pure refactoring. Any observable behavior
  change is a defect, not a feature. The engine must preserve dispatch
  behavior, state transitions, event emission, and gating outcomes across the
  existing prepare/work flows.
- **State compatibility**: existing todo state with in-progress work must
  continue to be read correctly. No offline migration step is acceptable.
- **Incremental mergeability**: the refactor must be deliverable without
  destabilizing main.
- **No new dependencies**: the refactor uses existing project dependencies
  only. No new third-party packages.

## Risks

- **Size**: this refactor spans lifecycle routing, dispatch surfaces,
  validation, and workflow definitions. The draft phase should confirm whether
  the work remains single-session sized or should be split into sequential
  sub-todos.
- **Behavioral drift**: subtle differences between engine output and current
  machine output could break orchestrator/worker contracts. Mitigation:
  behavioral equivalence tests comparing engine output against current machine
  output for each reachable state.
- **Legacy state derivation**: the current lifecycle can derive progress from
  existing artifacts for legacy or in-progress todos. The refactor must
  preserve those fallback paths.
- **Review/fix routing**: review rejections must re-enter the producing step
  with the same effective fix-loop semantics.
- **Human gate re-entry**: human-confirmed pauses must resume at the correct
  lifecycle point without losing context.

## Verification

- **Behavioral equivalence tests**: for each reachable prepare/work state,
  construct representative todo state and verify the refactored engine yields
  the same dispatch outcome as the current lifecycle.
- **Workflow definition validation**: workflow definitions load successfully
  and match the expected step progression.
- **Validation tests**: reusable validation paths produce the expected
  pass/fail outcomes for known inputs.
- **[inferred] Integration smoke**: run `telec todo prepare <slug>` and
  `telec todo work <slug>` against a representative test todo and verify the
  expected lifecycle progresses end to end.
- **Compatibility tests**: existing dispatch entry points continue to resolve
  to the correct lifecycle behavior during transition.
- **Language-aware step tests**: code-producing steps apply the correct
  language-specific conventions for representative project language setups.
