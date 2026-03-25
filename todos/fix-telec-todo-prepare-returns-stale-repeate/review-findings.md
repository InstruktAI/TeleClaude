# Review Findings: fix-telec-todo-prepare-returns-stale-repeate

**Review round:** 1
**Kind:** Bug fix
**Reviewer:** Claude (code review)

## Scope

Bug fix: `next_prepare` did not canonicalize `cwd` via `resolve_canonical_project_root`,
causing worktree paths to be used for all file lookups (roadmap, state, artifacts),
resulting in stale/repeated instructions.

Fix: one import and one `resolve_canonical_project_root` call at the top of `next_prepare`,
matching the established pattern in `next_work`.

Changed files:

- `teleclaude/core/next_machine/prepare.py`
- `tests/unit/core/next_machine/test_prepare.py`
- `todos/fix-telec-todo-prepare-returns-stale-repeate/bug.md`
- `todos/fix-telec-todo-prepare-returns-stale-repeate/state.yaml`

## Bug Fix Verification

- [x] Fix addresses the symptom described in `bug.md`
- [x] Root cause analysis is sound (missing canonicalization, same as `next_work` had)
- [x] Fix is minimal and targeted (one import, one line)
- [x] Investigation and documentation sections complete
- [x] Reproduction test exists (`test_next_prepare_canonicalizes_cwd_from_worktree_path`)
- [x] Reproduction test passes after the fix

## Lanes Executed

### Scope

Delivery matches bug description exactly. One import, one canonicalization call. No
unrequested features, no gold-plating.

No findings.

### Code (next-code-reviewer)

Production code is clean. The fix mirrors the established pattern in `next_work`
(`_normalize_next_work_cwd` at `work.py:174`). Import ordering is correct.
`cwd` reassignment propagates to all downstream calls.

No findings in production code.

### Paradigm

The fix follows the exact pattern from `next_work`:

- Same function (`resolve_canonical_project_root`)
- Same wrapping (`await asyncio.to_thread(...)`)
- Same placement (top of entry function, before any file access)
- Tests use the same mock patterns as existing tests

No findings.

### Principles

Checked: fallback/silent degradation, fail fast, DIP, coupling/Demeter, SRP, YAGNI/KISS,
encapsulation, immutability.

No violations in the changed code. `resolve_canonical_project_root` has a broad exception
catch that silently falls back to raw `cwd`, but this is pre-existing and not introduced
by this change.

No findings.

### Security

No new inputs, outputs, secrets, injection surfaces, or auth paths. The change operates
on local filesystem paths within the git repository.

No findings.

### Tests (next-test-analyzer)

Regression test is well-structured: verifies `resolve_canonical_project_root` is called
with the raw worktree path, and downstream calls (`read_phase_state`, `_prepare_dispatch`)
receive the canonicalized path. Existing tests correctly updated with `_identity`
passthrough mock.

One finding resolved during review (see below).

### Errors (next-silent-failure-hunter)

All findings are pre-existing in `resolve_canonical_project_root` (broad exception catch,
silent fallback). Not introduced by this change. No new silent failure paths.

No findings attributable to this change.

### Comments (next-comment-analyzer)

The inline comment in `prepare.py:74-77` is accurate, explains why (not what), and
correctly enumerates the downstream operations affected. Test docstring is clear.

No findings.

### Logging

No new logging added. Consistent with `next_work` which wraps canonicalization in a
helper that logs, but the minimal approach here is acceptable for a bug fix.

No findings.

### Demo

Bug fix — no demo.md required. Consistent with established project convention (no
other `kind: bug` items carry demo artifacts).

No findings.

### Docs

No CLI, config, API, or help text changes. No documentation updates required.

No findings.

## Resolved During Review

### Important: Wrong mock target for `check_artifact_staleness` in tests

**File:** `tests/unit/core/next_machine/test_prepare.py`, lines 39 and 105
**Severity:** Important (auto-remediated)

`check_artifact_staleness` was patched at the definition site
(`prepare_helpers.check_artifact_staleness`) instead of the lookup site
(`prepare.check_artifact_staleness`). Since `prepare.py` imports the function
directly, the mock at the source module had no effect — the real function ran
during tests. Tests passed by accident because the real function returns `[]`
for non-existent paths.

This was pre-existing from main but was copied into the new regression test.

**Fix applied:** Changed both mock targets from
`teleclaude.core.next_machine.prepare_helpers.check_artifact_staleness` to
`teleclaude.core.next_machine.prepare.check_artifact_staleness`.

All 4 tests pass after the fix.

## Suggestions

1. **Add debug log on canonicalization** — `next_work` logs when the path changes
   via `_normalize_next_work_cwd`. Adding a similar debug log in `next_prepare`
   would improve diagnostics consistency.

2. **Verify all downstream callers in regression test** — The regression test
   verifies `read_phase_state` and `_prepare_dispatch` receive the canonicalized
   path but does not check `resolve_holder_children` and `slug_in_roadmap`. Adding
   assertions for these would guard against a refactor that moves the
   canonicalization call below them.

## Why No Unresolved Issues

1. **Paradigm-fit verified:** The fix mirrors `next_work`'s established canonicalization
   pattern exactly — same function, same wrapping, same placement.
2. **Requirements verified:** Bug.md symptom is addressed; reproduction test confirms
   the fix; root cause analysis matches the code change.
3. **Copy-paste checked:** No duplication introduced. The `_identity` helper is shared
   across tests appropriately.
4. **Security reviewed:** No new attack surface.

## Verdict

**APPROVE**

Critical findings: 0
Important findings: 0 (1 auto-remediated)
Suggestions: 2
