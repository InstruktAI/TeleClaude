# DOR Report: demo-runner

## Gate Assessment

**Phase**: Gate (final)
**Date**: 2026-02-21
**Assessor**: Architect (gate mode)

## Gate Analysis

### 1. Intent & Success — PASS

- Problem statement is clear: demos should show working software, not AI narratives.
- Success criteria are concrete and testable (13 checkboxes).
- The "what" and "why" are well-articulated in `input.md` and `requirements.md`.

### 2. Scope & Size — PASS

- 9 files to edit/create, 1 to delete. Each change is small and concrete.
- The CLI runner (Phase 2) is the only substantial new code (~80-100 lines).
- Remaining work is spec/doc edits, test adjustments, agent command rewrite, and template config.
- Phases are sequential and well-ordered — no intermediate inconsistency risk.
- **Verdict**: Fits a single focused builder session.

### 3. Verification — PASS

- `make test` and `make lint` cover automated verification.
- Manual exercise: `telec todo demo` (list) and `telec todo demo tui-markdown-editor` (run).
- Edge cases identified: missing demo field, nonexistent slug, empty demos dir, semver mismatch.

### 4. Approach Known — PASS

- CLI subcommand pattern established (`_handle_todo` dispatches to `create`, `validate`; adding `demo` follows the pattern).
- `CLI_SURFACE["todo"].subcommands` dict pattern verified in codebase.
- `POST_COMPLETION` structure verified — `"next-finalize"` dispatches `"/next-demo"`, `"next-demo"` has own entry. Both need modification.
- Snapshot.json schema is simple JSON — adding optional `demo` field is backward compatible.
- Semver gating: `pyproject.toml` has `version = "0.1.0"` at line 7.

### 5. Research Complete — AUTO-PASS

- No third-party dependencies. All changes are internal.

### 6. Dependencies & Preconditions — PASS

- No prerequisite todos.
- No external system dependencies.
- All referenced files exist and are accessible (verified: `demo-artifact.md`, `core.py`, `test_next_machine_demo.py`, `next-demo.md`, `quality-checklist.md` template, `demo.md` procedure doc, `snapshot.json`, `demo.sh`).
- **Action required**: Add `demo-runner` to `roadmap.yaml` before build dispatch.

### 7. Integration Safety — PASS

- Atomic merge to main. No intermediate broken state.
- Removing demo from finalize POST_COMPLETION is safe — it was already non-blocking.
- Backward compatibility: runner handles demos without `demo` field (warn + skip execution).

### 8. Tooling Impact — PASS

- CLI surface change: `telec todo demo` subcommand. Plan Task 2.1 covers this explicitly.
- Quality checklist template: Plan Task 3.4 adds the build gate.
- `/next-demo` agent command: Plan Task 3.3 rewrites it as builder guidance + presentation runner. This serves as the "how to write a demo" procedure.
- Demo artifact spec: Plan Task 1.1 updates the schema documentation.
- All tooling changes are accounted for in the implementation plan.

## Assumptions (validated)

1. The `demo` field is a shell command string, not a structured object. Simple and sufficient.
2. `demos/001-tui-markdown-editor/` is the only demo to migrate. Confirmed — only one demo directory exists.
3. Semver gate uses major-version comparison. Current version is `0.1.0`.
4. `POST_COMPLETION["next-finalize"]` step 3 (DEMO) and `POST_COMPLETION["next-demo"]` entry both need modification. Confirmed in `core.py` lines 144-161.

## Open Questions

1. **Demo field format**: String vs structured object. String is the right call for now — no extensibility needed yet, and it can evolve later without breaking changes.

## Blockers

- None.

## Gate Verdict

**Score**: 8/10
**Status**: `pass`

**Reasoning**: All 8 DOR gates pass. The scope concern from the draft phase (7/10) is resolved — each individual change is small and the implementation plan provides clear, concrete tasks. The tooling impact concern is resolved — all procedure/template/spec changes are explicitly covered. The only pre-build action is adding `demo-runner` to `roadmap.yaml`.

## Actions Taken

- Verified all file references against codebase (all exist).
- Verified CLI_SURFACE pattern and \_handle_todo dispatcher structure.
- Verified POST_COMPLETION structure and exact entries to modify.
- Verified snapshot.json schema compatibility.
- Verified pyproject.toml version field location.
- Elevated score from 7 to 8 based on evidence.
- Set gate status to `pass`.
