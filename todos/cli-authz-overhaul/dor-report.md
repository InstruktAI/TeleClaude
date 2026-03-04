# DOR Report: cli-authz-overhaul

## Gate Assessment

**Date:** 2026-03-03
**Assessor:** Gate (formal DOR validation)
**Status:** Pass
**Score:** 9/10

## Gate Results

### 1. Intent & Success — PASS

The problem is explicit: authorization is scattered across deny-list sets in `tool_access.py`,
`CLEARANCE_*` constants in `api/auth.py`, and absent for ~50 commands that lack any gate.
The intended outcome is clear: `CommandAuth` on every `CommandDef` + `is_command_allowed()`
as the single source of truth. Success criteria are concrete and testable — six verifiable
checkboxes covering data model, function behavior, test coverage, and doc alignment.

### 2. Scope & Size — PASS

The original input describes 11 workstreams. This todo is correctly scoped to **Workstream 1
only**: the `CommandAuth` dataclass, `is_command_allowed()`, and auth metadata population.
The work is additive (no breaking changes), touches primarily `telec.py` and a new test file,
and fits a single AI session. Follow-on workstreams are identified with dependency graph.

### 3. Verification — PASS

Verification paths are well-defined:
- Unit tests for `is_command_allowed()` covering all role combinations (11 test cases specified).
- Completeness test asserting every leaf `CommandDef` has `auth` populated.
- `make test` and `make lint` gates.
- Demo script with inline validation assertions.

### 4. Approach Known — PASS

The approach is straightforward and uses existing patterns:
- `CommandAuth` is a frozen dataclass added to the existing `CommandDef` schema (verified:
  `CommandDef` at `telec.py:104`, `CLI_SURFACE` at `telec.py:132`).
- Role constants already exist in `teleclaude/constants.py` (`ROLE_WORKER`, `ROLE_ORCHESTRATOR`,
  `HUMAN_ROLE_ADMIN`, `HUMAN_ROLE_MEMBER`, etc.).
- The authorization matrix is already designed with user-confirmed corrections captured in
  requirements.

Design decisions are resolved:
- `exclude_human` field on `CommandAuth` for the `sessions escalate` admin exclusion.
- `todo demo` expanded into explicit subcommand `CommandDef` entries (currently a positional
  arg handler at `telec.py:2170`).
- `config people` and `config env` expanded into real leaf subcommands (currently using
  `HELP_SUBCOMMAND_EXPANSIONS` at `telec.py:612`).

### 5. Research Complete — PASS (N/A)

No third-party dependencies. Purely internal code.

### 6. Dependencies & Preconditions — PASS

No prerequisite todos. All needed files are identified and verified in the codebase:
- `teleclaude/cli/telec.py` — primary target, `CommandDef` and `CLI_SURFACE` confirmed.
- `teleclaude/constants.py` — role constants confirmed present.
- `docs/project/design/cli-authorization-matrix.md` — exists, corrections to apply are explicit.
- `tests/unit/test_command_auth.py` — new file, no conflicts.
- `api/auth.py` does NOT currently import from `teleclaude.cli`, so no circular import risk
  for this workstream. The import concern is only relevant when WS8 wires the API.

### 7. Integration Safety — PASS

Purely additive:
- New `CommandAuth` dataclass and optional `auth` field on existing `CommandDef`.
- New `is_command_allowed()` function.
- No existing code modified or deleted.
- Legacy `tool_access.py` and `CLEARANCE_*` constants remain functional.
- Rollback is trivial: revert the commit.

### 8. Tooling Impact — PASS (N/A)

No tooling or scaffolding changes. `telec sync` and artifact generation unaffected.

## Plan-to-Requirement Fidelity — PASS

Every implementation task traces to a requirement:
- Task 1.1 → Req: CommandAuth dataclass + auth field on CommandDef
- Task 1.2 → Req: Role constants (supports readability of CLI_SURFACE)
- Task 1.3 → Req: is_command_allowed() with two-axis composition
- Task 2.1 → Req: Populate auth on every leaf command
- Task 2.2 → Req: todo demo sub-subcommand auth (structural prerequisite)
- Task 2.3 → Req: config people/env expansion (structural prerequisite)
- Task 3.1 → Req: Update cli-authorization-matrix.md with corrections
- Task 4.1–4.3 → Req: Unit tests and quality checks

No task contradicts a requirement. The implementation plan's auth tables are consistent with
the user-confirmed corrections in requirements (not the pre-correction matrix document).

## Builder Notes

1. **`todo demo` expansion**: Expanding into real subcommands may require dispatch
   adjustments in `_handle_todo_demo()` (`telec.py:2170`). The positional-arg parser
   currently handles `list|validate|run|create` as arguments, not subcommands. Verify
   dispatch still works after the structural change.

2. **`config people`/`config env` expansion**: Currently these are non-leaf nodes
   using `HELP_SUBCOMMAND_EXPANSIONS` (`telec.py:612`). Expanding into real leaf
   `CommandDef` entries should make `HELP_SUBCOMMAND_EXPANSIONS` obsolete for these
   commands. Clean up the expansion table accordingly.

3. **Circular import (WS8 concern, not WS1)**: `api/auth.py` does not currently import
   from `teleclaude.cli`. The `is_command_allowed()` function just needs to be importable.
   If WS8 hits import cycles, extract to `teleclaude/cli/command_auth.py`.

## Assumptions (Accepted)

- User-confirmed corrections are final.
- Admin-implicit convention (admin bypasses human-role check) applies to all commands
  except `sessions escalate`.
- `None` system_role (non-session callers) treated as orchestrator.

## Summary

All eight DOR gates pass. The scope is atomic (WS1 only), the approach is known and
grounded in existing codebase patterns, and the verification path is clear. The primary
work is mechanical: populating auth metadata on ~65 leaf commands using a reviewed
authorization matrix. The completeness test prevents future regressions.
