# Plan Review Findings: agent-cli-context-preservation

## Round 2 (current)

All findings were remediated inline. No unresolved findings remain.

### Finding 1 — Critical (demo accuracy) — RESOLVED

`demo.md` Block 1 imported `configure_agent_cli` as a function. No such function exists in
`install_hooks.py` (the source for the renamed `configure_agent_cli` module). The module exports
`configure_claude`, `configure_codex`, and `configure_gemini`. The non-existent import would
cause an `ImportError` at demo run time.

**Fix:** Removed `configure_agent_cli` from the import list in `demo.md` Block 1.

### Finding 2 — Important (Task 5.1 scope description) — RESOLVED

Task 5.1 said to remove xfail markers "as each R1/R4 behavior is satisfied." The test file
`test_configure_agent_cli.py` covers R1, R2, R3, and R4 — not just R1 and R4.

**Fix:** Updated Task 5.1 to say "R1/R2/R3/R4 behavior."

### Finding 3 — Important (missing per-task verification steps) — RESOLVED

Tasks 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, and 4.1 lacked explicit verification steps
referencing specific expected-failure tests. Policy requires every task to include a verification
step that names the tests it makes GREEN (or the behavior to observe).

**Fix:** Added `**Tests made GREEN:**` pointers to each affected task, mapping each task to its
corresponding spec tests from `test_configure_agent_cli.py` and `test_distribute.py`.

### Suggestion — Phase numbering — RESOLVED

Phase numbering jumped from Phase 6 to Phase 8 (no Phase 7). Corrected to Phase 7.

---

## Round 1 (previous — all resolved before this round)

### Critical (resolved in round 1) — Task 3.2 wrapping approach incompatible with approved test specs

Task 3.2 originally specified wrapping at `_run_phase`. The approved spec tests call
`dump_frontmatter` and `transform_to_codex` directly. Resolution: Task 3.2 updated to wrap
inside `dump_frontmatter`.

### Important (resolved in round 1) — `state.yaml.grounding.referenced_paths` missing test spec files

Both test spec file paths added to `referenced_paths`.

### Important (resolved between rounds) — Plan missing demo.md population task

Task 6.1 added to Phase 6; `demo.md` populated with executable verification blocks.

---

## Verdict: APPROVE

Unresolved Critical findings: 0
Unresolved Important findings: 0
All findings resolved during review.
