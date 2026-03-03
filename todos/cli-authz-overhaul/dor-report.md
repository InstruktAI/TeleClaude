# DOR Report: cli-authz-overhaul

## Draft Assessment

**Date:** 2026-03-03
**Assessor:** Draft phase (prepare router)
**Status:** Draft — pending formal gate validation

## Gate Assessment

### 1. Intent & Success

**Status: PASS**

The problem is explicit: authorization is scattered across deny-list sets in `tool_access.py`,
`CLEARANCE_*` constants in `api/auth.py`, and nowhere for ~50 commands that lack any gate.
The intended outcome is clear: `CommandAuth` on every `CommandDef` + `is_command_allowed()`
as the single source of truth. Success criteria are concrete and testable.

### 2. Scope & Size

**Status: PASS (after scoping)**

The original input describes 11 workstreams — far too large for a single todo. This draft
scopes the todo to **Workstream 1 only**: CommandAuth metadata and `is_command_allowed()`.
This is additive (no breaking changes), touches primarily `telec.py` and a new test file,
and fits a single AI session.

**Follow-on todos needed (not created yet — the gate or orchestrator should create them):**

| Slug (suggested) | Workstream | Depends on |
|---|---|---|
| `cli-authz-mandatory-roles` | WS4: Mandatory session fields, kill heuristic | independent |
| `cli-authz-role-help` | WS3: Role-aware `telec -h` | cli-authz-overhaul |
| `cli-authz-new-commands` | WS7: New CLI commands (todo list, jobs, settings, notifications) | cli-authz-overhaul |
| `cli-authz-api-migration` | WS8: Cover all API routes with `is_command_allowed()` | cli-authz-overhaul, cli-authz-new-commands |
| `cli-authz-kill-legacy` | WS2: Delete `tool_access.py`, `CLEARANCE_*` constants | cli-authz-api-migration |
| `cli-authz-baselines` | WS5+WS6: Role-filtered baselines + session injection | cli-authz-overhaul, cli-authz-role-help |
| `cli-authz-project-ownership` | WS9: Project ownership model | cli-authz-mandatory-roles |
| `cli-authz-docs` | WS10+WS11: Documentation updates | all above |

### 3. Verification

**Status: PASS**

Verification paths are clear:
- Unit tests for `is_command_allowed()` covering all role combinations.
- Completeness test ensuring every leaf command has `auth` populated.
- `make test` and `make lint` pass.
- Demo script validates auth metadata and function behavior.

### 4. Approach Known

**Status: PASS**

The approach is straightforward:
- `CommandAuth` is a frozen dataclass added to the existing `CommandDef` schema.
- `is_command_allowed()` walks `CLI_SURFACE` to find the command and checks the two-axis rule.
- The authorization matrix (`cli-authorization-matrix.md`) is already designed and has user-confirmed corrections.
- No architectural decisions remain unresolved.

**Design decision: `exclude_human` field.** The `sessions escalate` command needs admin
excluded. Two options: (a) add an `exclude_human` field to `CommandAuth`, (b) hardcode the
exception in `is_command_allowed()`. Recommend (a) for explicitness and consistency with
the allow-list model.

**Design decision: `todo demo` sub-subcommands.** Currently `todo demo` takes a positional
arg (`list|validate|run|create`). The plan recommends expanding these into explicit
subcommand `CommandDef` entries so auth can be uniform. This is a minor structural change
to `CLI_SURFACE` and should not affect runtime dispatch (which already parses the positional).

**Design decision: `config people` and `config env` expansion.** Currently these use
`HELP_SUBCOMMAND_EXPANSIONS` for display but don't have real leaf `CommandDef` entries.
Expanding them into real subcommands keeps auth uniform. The help-expansion hack can be
removed once they're real entries.

### 5. Research Complete

**Status: PASS (N/A)**

No third-party dependencies. This is purely internal code.

### 6. Dependencies & Preconditions

**Status: PASS**

No prerequisite todos. The authorization matrix design doc already exists and has been
reviewed with user corrections. All needed files are identified:
- `teleclaude/cli/telec.py` — primary change target
- `teleclaude/constants.py` — role constants (already defined)
- `docs/project/design/cli-authorization-matrix.md` — corrections to apply
- `tests/unit/test_command_auth.py` — new test file

### 7. Integration Safety

**Status: PASS**

This change is purely additive:
- New `CommandAuth` dataclass and `auth` field added to existing structures.
- New `is_command_allowed()` function added.
- No existing code is modified or deleted.
- No existing behavior changes.
- Legacy `tool_access.py` and `CLEARANCE_*` constants remain functional.
- Rollback is trivial: revert the commit.

### 8. Tooling Impact

**Status: PASS (N/A)**

No tooling or scaffolding changes required. `telec sync` and artifact generation are unaffected.

## Open Questions

1. **`todo demo` expansion**: Expanding into real subcommands may require changes to
   the dispatch path in `telec.py` if the positional-arg parser doesn't handle the
   new structure. The builder should verify dispatch still works.

2. **Import path for `is_command_allowed()`**: `telec.py` currently imports from
   `teleclaude.constants`. The API module `api/auth.py` would import from `teleclaude.cli.telec`.
   Verify this doesn't create circular imports. If it does, extract `is_command_allowed()`
   to a standalone module (e.g., `teleclaude/cli/command_auth.py`).

## Assumptions

- The user-confirmed corrections are final and do not require further review.
- Admin-implicit convention (admin bypasses human-role check) is the desired behavior
  for all commands except `sessions escalate`.
- `None` system_role (non-session callers) should be treated as orchestrator for the
  system-role check, since non-session callers are never workers.

## Summary

This todo is scoped to the foundational workstream. All DOR gates pass. The main work is
mechanical: populating auth metadata on ~65 leaf commands using a reviewed and corrected
authorization matrix. The primary risk is completeness — the test for "every leaf has auth"
mitigates this.

**Draft score: 9/10** — all gates satisfied, scope is atomic, approach is known, no blockers.
