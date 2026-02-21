# DOR Report: demo-runner

## Draft Assessment

**Phase**: Draft (revision 2)
**Date**: 2026-02-21
**Assessor**: Architect (draft mode)

## Artifact State

State D: Both `requirements.md` and `implementation-plan.md` existed from a prior draft. This revision tightens both against verified codebase state — actual file contents, line numbers, field names, and existing test coverage.

**Codebase verification performed**:

- CLI surface structure in `telec.py` (lines 143-162, 1050-1064) — confirmed dispatcher pattern
- `POST_COMPLETION` dict in `core.py` (lines 80-125) — confirmed `next-finalize` step 3 and `next-demo` entry
- Both existing demo folders inspected — actual `snapshot.json` field names documented
- `test_next_machine_demo.py` (359 lines) — test expectations vs actual snapshot fields mapped
- Quality checklist template — no demo gate present
- Demo procedure doc — references `delivered.md` (actual file is `delivered.yaml`)
- Project version: `0.1.0`

## Draft Analysis

### 1. Intent & Success

- Problem statement is clear: demos should show working software, not AI narratives.
- Success criteria are concrete and testable (19 checkboxes).
- The "what" and "why" are well-articulated across `input.md` and `requirements.md`.
- **Assessment**: Strong. No gaps.

### 2. Scope & Size

- ~10 files to edit/create, 2 to rename, 2 to delete.
- CLI runner (~80-100 lines) is the only substantial new code.
- Remaining: spec/doc edits, test updates, agent command rewrite, template config.
- 5 sequential phases, well-ordered.
- **Assessment**: Fits a single focused builder session.

### 3. Verification

- `make test` and `make lint` cover automated verification.
- Manual: `telec todo demo` (list) and `telec todo demo tui-markdown-editor` (run).
- Edge cases identified: missing demo field, nonexistent slug, empty demos dir, semver mismatch.
- **Assessment**: Clear verification path.

### 4. Approach Known

- CLI subcommand pattern established: `CLI_SURFACE["todo"].subcommands` has `create` and `validate`; adding `demo` follows the same pattern.
- `_handle_todo()` dispatches to `_handle_todo_create()` and `_handle_todo_validate()`; adding `_handle_todo_demo()` is mechanical.
- `POST_COMPLETION` structure verified — removing entries and steps is straightforward.
- **Assessment**: Known pattern, no architectural decisions needed.

### 5. Research Complete — AUTO-PASS

- No third-party dependencies. All changes are internal.

### 6. Dependencies & Preconditions

- No prerequisite todos in roadmap.
- All referenced files exist and are accessible.
- **Assessment**: No blockers.

### 7. Integration Safety

- Atomic merge to main. No intermediate broken state if phases are committed in order.
- Removing demo from finalize POST_COMPLETION is safe — it was already non-blocking.
- Backward compatibility: runner handles demos without `demo` field.
- **Assessment**: Safe.

### 8. Tooling Impact

- CLI surface change: `telec todo demo` subcommand (Task 2.1).
- Quality checklist template: demo gate (Task 3.3).
- `/next-demo` command rewrite (Task 3.2).
- Demo artifact spec update (Task 1.1).
- Demo procedure doc update (Task 3.4).
- **Assessment**: All tooling changes accounted for in the plan.

## Assumptions

1. The `demo` field is a shell command string, not a structured object.
2. Folder rename from `demos/NNN-{slug}/` to `demos/{slug}/` is safe — only two existing demos.
3. Semver gate uses major-version comparison only. Current project version is `0.1.0`.
4. Existing snapshot field name inconsistencies are left as-is (out of scope). The runner reads actual field names with fallbacks.
5. The Five Acts narrative structure is preserved — builders compose it during build instead of AI composing it post-finalize.

## Noted Risks

1. **Test-schema mismatch**: `test_next_machine_demo.py` uses spec-standard field names (`delivered`, `commit`, `lines_added`, `lines_removed`, `whats_next`) but actual snapshot files use variant names (`delivered_date`, `merge_commit`, `insertions`, `deletions`, `next`). Tests that validate the schema will need careful handling — either test against what the runner actually reads, or keep tests validating the spec-standard schema for _new_ demos going forward.
2. **Workflow shift**: Builders now create demos during build. This needs explicit guidance in the procedure doc (Task 3.4).

## Open Questions

None — previous user clarification resolved folder naming and interface questions. Schema normalization was explicitly placed out of scope.

## Blockers

None.

## Draft Verdict

**Estimated score**: 8/10
**Status**: Artifacts are substantive, codebase-verified, and ready for formal gate assessment.
**Next step**: Route to `next-prepare-gate` for formal DOR validation.

## Actions Taken (this revision)

- Tightened requirements: added presentation details (widget rendering), explicit schema field-name constraint, `delivered.yaml` reference fix, builder guidance as in-scope item, `POST_COMPLETION["next-demo"]` removal.
- Tightened implementation plan: verified line numbers against codebase, added field-name fallback handling in runner, added builder guidance task in procedure doc, fixed `delivered.md` → `delivered.yaml`, added build sequence summary table, added specific test removal targets.
- DOR report: full codebase verification performed, schema mismatch documented as noted risk with mitigation path.
