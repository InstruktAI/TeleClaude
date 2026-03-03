# Implementation Plan: cli-authz-overhaul

## Overview

Add `CommandAuth` metadata to the existing `CommandDef` schema and implement `is_command_allowed()`
as the canonical authorization function. This is additive — no existing code is modified or deleted.
The legacy `tool_access.py` deny-lists and `CLEARANCE_*` constants remain functional and are
replaced in follow-on workstreams.

## Phase 1: Core Model

### Task 1.1: Add `CommandAuth` dataclass

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `CommandAuth` dataclass adjacent to `CommandDef`:
  ```python
  @dataclass(frozen=True)
  class CommandAuth:
      system: frozenset[str]   # allowed system roles
      human: frozenset[str]    # allowed human roles (admin always implicit except escalate)
  ```
- [ ] Add optional `auth: CommandAuth | None = None` field to `CommandDef`

### Task 1.2: Define role constants for auth

**File(s):** `teleclaude/cli/telec.py`

- [ ] Import `ROLE_WORKER`, `ROLE_ORCHESTRATOR`, and human role constants from `teleclaude.constants`
- [ ] Define shorthand sets for common role patterns to keep `CLI_SURFACE` readable:
  ```python
  _SYS_ORCH = frozenset({ROLE_ORCHESTRATOR})        # orchestrator only
  _SYS_ALL = frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR})  # both system roles
  _HR_ADMIN_ONLY = frozenset()                       # admin implicit, no others
  _HR_ADMIN_MEMBER = frozenset({HUMAN_ROLE_MEMBER})  # admin + member
  # ... etc, as needed for the matrix
  ```
- [ ] Keep these as module-level constants in `telec.py`, near `CLI_SURFACE`

### Task 1.3: Implement `is_command_allowed()`

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add function that resolves a command path to its `CommandAuth` and checks the two-axis rule:
  ```
  allowed = (system_role in auth.system) AND (human_role == "admin" OR human_role in auth.human)
  ```
- [ ] Special case: `sessions escalate` — admin is explicitly excluded. Implement via an
  `exclude_human: frozenset[str]` field on `CommandAuth` (default empty), or by checking
  the command path. Prefer the field approach for explicitness.
- [ ] Handle `None` system_role (non-session callers like TUI/terminal): treat as orchestrator
  for system-role check (non-session callers are never workers).
- [ ] Handle `None` human_role: deny all human-role-gated commands (fail closed).
- [ ] Return `False` for unknown command paths (fail closed).

---

## Phase 2: Populate Auth Metadata

### Task 2.1: Populate auth on every leaf command in CLI_SURFACE

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `auth=CommandAuth(...)` to every leaf `CommandDef` in `CLI_SURFACE`, following
  the corrected authorization matrix. The complete per-command auth is:

**Sessions:**

| Command | system | human (besides admin) |
|---|---|---|
| `sessions list` | orch | member, contributor, newcomer |
| `sessions start` | orch | member |
| `sessions send` | orch | member |
| `sessions tail` | orch | member, contributor, newcomer |
| `sessions run` | orch | member |
| `sessions revive` | orch | (admin only) |
| `sessions end` | orch | member |
| `sessions unsubscribe` | orch | member |
| `sessions restart` | orch | (admin only) |
| `sessions result` | all | member, contributor |
| `sessions file` | all | member, contributor |
| `sessions widget` | all | member, contributor |
| `sessions escalate` | all | member, contributor, newcomer, customer (admin EXCLUDED) |

**Infrastructure:**

| Command | system | human (besides admin) |
|---|---|---|
| `computers list` | orch | member |
| `projects list` | orch | member, contributor, newcomer |
| `agents availability` | orch | member, contributor, newcomer |
| `agents status` | orch | (admin only) |
| `channels list` | orch | member |
| `channels publish` | orch | member |

**System:**

| Command | system | human (besides admin) |
|---|---|---|
| `init` | orch | member |
| `version` | all | member, contributor, newcomer, customer |
| `sync` | orch | member |
| `watch` | orch | member |

**Docs:**

| Command | system | human (besides admin) |
|---|---|---|
| `docs index` | all | member, contributor, newcomer, customer |
| `docs get` | all | member, contributor, newcomer, customer |

**Todo Management:**

| Command | system | human (besides admin) |
|---|---|---|
| `todo create` | orch | member, contributor |
| `todo remove` | orch | member |
| `todo validate` | all | member, contributor, newcomer |
| `todo demo list` | all | member, contributor, newcomer |
| `todo demo validate` | all | member, contributor, newcomer |
| `todo demo run` | all | member, contributor |
| `todo demo create` | orch | member, contributor |
| `todo prepare` | orch | member |
| `todo work` | orch | member |
| `todo mark-phase` | orch | member |
| `todo set-deps` | orch | member |
| `todo verify-artifacts` | all | member, contributor, newcomer |
| `todo dump` | all | member, contributor |

**Roadmap:**

| Command | system | human (besides admin) |
|---|---|---|
| `roadmap list` | orch | member, contributor, newcomer |
| `roadmap add` | orch | member |
| `roadmap remove` | orch | member |
| `roadmap move` | orch | member |
| `roadmap deps` | orch | member |
| `roadmap freeze` | orch | member |
| `roadmap deliver` | orch | member |

**Bugs:**

| Command | system | human (besides admin) |
|---|---|---|
| `bugs report` | all | member, contributor, newcomer |
| `bugs create` | orch | member, contributor |
| `bugs list` | all | member, contributor, newcomer |

**Content:**

| Command | system | human (besides admin) |
|---|---|---|
| `content dump` | all | member, contributor |

**Events:**

| Command | system | human (besides admin) |
|---|---|---|
| `events list` | all | member, contributor, newcomer |

**Auth:**

| Command | system | human (besides admin) |
|---|---|---|
| `auth login` | all | member, contributor, newcomer, customer |
| `auth whoami` | all | member, contributor, newcomer, customer |
| `auth logout` | all | member, contributor, newcomer, customer |

**Config:**

| Command | system | human (besides admin) |
|---|---|---|
| `config wizard` | orch | (admin only) |
| `config get` | all | member, contributor, newcomer |
| `config patch` | orch | (admin only) |
| `config validate` | all | member, contributor, newcomer |
| `config people list` | orch | (admin only) |
| `config people add` | orch | (admin only) |
| `config people edit` | orch | (admin only) |
| `config people remove` | orch | (admin only) |
| `config env list` | orch | (admin only) |
| `config env set` | orch | (admin only) |
| `config notify` | orch | member |
| `config invite` | orch | (admin only) |

### Task 2.2: Handle `todo demo` sub-subcommands

**File(s):** `teleclaude/cli/telec.py`

- [ ] The `todo demo` command takes a positional arg (`list|validate|run|create`) rather
  than having explicit subcommand `CommandDef` entries. Decide how to represent auth:
  - Option A: Expand `todo demo` into explicit subcommand entries in `CLI_SURFACE`.
  - Option B: Add auth at the `todo demo` level and handle sub-action gating separately.
  - Preferred: Option A — expand into `demo list`, `demo validate`, `demo run`, `demo create`
    as explicit subcommands. This keeps the auth model uniform.

### Task 2.3: Handle `config people` and `config env` sub-subcommands

**File(s):** `teleclaude/cli/telec.py`

- [ ] These currently use `HELP_SUBCOMMAND_EXPANSIONS` for display but don't have explicit
  leaf `CommandDef` entries. Expand them into real subcommands:
  - `config people list`, `config people add`, `config people edit`, `config people remove`
  - `config env list`, `config env set`
  - Each gets its own `CommandDef` with `auth` populated.

---

## Phase 3: Update Authorization Matrix Document

### Task 3.1: Apply corrections to the matrix document

**File(s):** `docs/project/design/cli-authorization-matrix.md`

- [ ] Update `sessions end` row: add member ✅ (self-scoped at API layer)
- [ ] Update `sessions restart` row: remove member, keep admin only
- [ ] Update `sessions revive` row: remove member, keep admin only
- [ ] Verify `sessions escalate` row already shows admin ❌, worker ✅
- [ ] Verify `roadmap list` row already shows worker ❌
- [ ] Add note about self-scoping for `sessions end` (member can only end own sessions)

---

## Phase 4: Validation

### Task 4.1: Unit tests for `is_command_allowed()`

**File(s):** `tests/unit/test_command_auth.py` (new)

- [ ] Test admin bypasses human-role check for all commands
- [ ] Test admin is DENIED `sessions escalate`
- [ ] Test worker is denied orchestrator-only commands
- [ ] Test worker is allowed worker-permitted commands (result, file, widget, escalate, docs, etc.)
- [ ] Test member permissions match the matrix
- [ ] Test contributor restrictions (no session start/send/run)
- [ ] Test newcomer restrictions (read-heavy)
- [ ] Test customer restrictions (only version, docs, auth, escalate)
- [ ] Test unknown command path returns False
- [ ] Test None system_role treated as orchestrator
- [ ] Test None human_role denied for all human-gated commands

### Task 4.2: Completeness test — every leaf has auth

**File(s):** `tests/unit/test_command_auth.py` (new)

- [ ] Walk `CLI_SURFACE` recursively, collect all leaf `CommandDef` nodes
- [ ] Assert every leaf has `auth is not None`
- [ ] This test prevents future regressions when new commands are added without auth

### Task 4.3: Quality checks

- [ ] Run `make lint`
- [ ] Run `make test`

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document follow-on todos needed (WS2-WS11) in deferrals if applicable
