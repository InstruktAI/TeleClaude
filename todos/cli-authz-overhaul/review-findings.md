# Review Findings: cli-authz-overhaul

## Review Scope

- Branch: `cli-authz-overhaul` vs `main`
- Changed files: `teleclaude/cli/telec.py`, `tests/unit/test_command_auth.py`, `docs/project/design/cli-authorization-matrix.md`, `demos/cli-authz-overhaul/demo.md`, `teleclaude/core/next_machine/core.py` (trivial whitespace)

## Critical

### C1: 9 commands deny workers despite matrix granting worker access

**Location:** `teleclaude/cli/telec.py` (multiple `CommandDef` entries)

The authorization matrix document (`docs/project/design/cli-authorization-matrix.md`) shows **Worker ✅** with explicit reasoning for 9 commands, but the code uses `_SYS_ORCH` (orchestrator only), blocking workers. The requirements state: "Ensure consistency with `docs/project/design/cli-authorization-matrix.md`."

| Command | Matrix Worker | Code | Should be |
|---|---|---|---|
| `sessions list` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `sessions send` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `sessions tail` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `sessions unsubscribe` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `computers list` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `projects list` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `agents availability` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `channels list` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |
| `channels publish` | ✅ | `_SYS_ORCH` | `_SYS_ALL` |

The matrix reasoning explicitly documents WHY workers need these (peer collaboration, environment awareness, status publishing). The implementation plan tables incorrectly listed these as `orch` only, contradicting the matrix that the requirements designate as authoritative.

**Fix:** Change `system=_SYS_ORCH` to `system=_SYS_ALL` for all 9 commands. Add test cases in `TestWorkerAllowed` to verify workers can access these commands.

## Important

None.

## Suggestions

### S1: `_HR_ALL_NON_ADMIN` and `_HR_ALL` are identical frozensets

**Location:** `teleclaude/cli/telec.py:187-188`

Both constants contain `{HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER}`. Since the `human` field always implies admin-implicit access, and admin exclusion is handled by `exclude_human`, one constant suffices. The naming distinction is semantic sugar that creates maintenance risk (new human roles must be added to both).

**Suggestion:** Remove `_HR_ALL_NON_ADMIN` and use `_HR_ALL` for `sessions escalate`. The `exclude_human` field already makes the admin exclusion explicit.

### S2: Matrix document lacks coverage for some leaf commands

**Location:** `docs/project/design/cli-authorization-matrix.md`

The following commands have auth in the code but are not in the matrix document: `todo integrate`, `history search`, `history show`, `memories search/save/delete/timeline`. The auth values assigned are reasonable but unspecified in the spec. Consider adding them to the matrix in a follow-up.

## Paradigm-Fit Assessment

- **Data flow:** Follows established patterns. `CommandAuth` is co-located with `CLI_SURFACE` per the `CommandDef` schema pattern.
- **Component reuse:** Role constants imported from `teleclaude.constants` (single source of truth). Auth shorthand constants reused across `CLI_SURFACE` entries.
- **Pattern consistency:** Frozen dataclass follows existing `Flag` pattern. `is_command_allowed()` follows the established function-based API in `telec.py`.

## Principle Violation Hunt

- **Fallback/Silent Degradation:** None. All failure paths return `False` (fail closed). Unknown paths, None roles all correctly denied.
- **Fail Fast:** `is_command_allowed()` fails closed everywhere. No defensive fallbacks.
- **DIP:** Clean. `telec.py` imports only from `teleclaude.constants` (no adapter imports).
- **Coupling:** Minimal. Auth metadata is self-contained within `CommandDef`.
- **SRP:** `CommandAuth` has a single responsibility (auth metadata). `is_command_allowed()` is a pure function.
- **YAGNI/KISS:** `exclude_human` field is used for one command, but the alternative (special-casing in the function) would be less explicit. Acceptable.
- **Encapsulation:** `CommandAuth` is frozen. Auth checking goes through the function, not direct field access.
- **Immutability:** All auth constants are frozensets. `CommandAuth` is frozen dataclass.

## Demo Review

3 executable bash blocks verified:
1. **Leaf completeness check** — imports `CLI_SURFACE`, `CommandDef`, walks tree, asserts auth populated. Cross-checked against code: imports exist, fields exist. Valid.
2. **Authorization check exercise** — imports `is_command_allowed`, tests admin bypass/exclusion, worker restrictions, customer restrictions, None human role. Cross-checked: all assertions match code behavior. Valid.
3. **`make test`** — standard test suite run. Valid.

Guided presentation (Steps 1-5) references real code structures and provides domain-specific walkthrough. Not shallow.

## Test Coverage Assessment

- 74 tests across 10 test classes covering all role combinations, edge cases, path format normalization.
- Completeness regression test (`test_every_leaf_has_auth`) prevents future commands from missing auth.
- **Gap:** No tests verify that workers ARE allowed the 9 mismatched commands (sessions list/send/tail/unsubscribe, computers list, projects list, agents availability, channels list/publish). Current `TestWorkerAllowed` only covers `_SYS_ALL` commands. This gap is caused by C1 — fix C1 and add corresponding tests.

## Verdict: REQUEST CHANGES

1 Critical finding must be resolved: the system-role gate for 9 commands contradicts the authoritative matrix document.
