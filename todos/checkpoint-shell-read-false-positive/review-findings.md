# Review Findings: checkpoint-shell-read-false-positive

**Type:** Bug fix review
**Reviewer:** Claude (review session)
**Round:** 1

---

## Scope (bug fix)

The fix addresses exactly the symptom in `bug.md`: read-only shell commands (grep, cat, git diff)
were extracting file paths into `touched_files`, causing false-positive checkpoint attribution when
those paths overlapped with pre-existing dirty files. The fix gates `_extract_shell_touched_paths()`
behind `_command_likely_mutates_files()`. No unrequested features or scope creep.

Bug.md sections (Investigation, Root Cause, Fix Applied) are complete and accurate.
Reproduction test exists and directly exercises the bug scenario.

No findings.

## Code (next-code-reviewer)

The fix is a 6-line reorder within `_extract_turn_file_signals()` — moving path extraction inside
the mutation guard. No new abstractions, no new control flow. The change is semantically correct:
compound commands like `grep ... && sed -i ...` are still handled because `_command_likely_mutates_files`
scans the full command string.

No findings.

## Paradigm

The fix follows the existing code's pattern exactly — same function, same block structure, same
variable names. The regression test follows the same pattern as the adjacent
`test_scope_git_files_to_current_turn_uses_only_turn_local_file_signals` test.

No findings.

## Principles (principle-violation-hunt)

Checked: fallback/silent-degradation, fail-fast, DIP, coupling, SRP, YAGNI/KISS, encapsulation,
immutability.

The fix tightens the mutation gate. Downstream behavior is consistently fail-closed:
when the classifier misses a mutation, `_scope_git_files_to_current_turn` returns `[]` (lines 397-399),
which is the safer direction (under-counting vs. false-positives). No unjustified fallbacks.

No findings.

## Security

No secrets, no user input, no injection surface. Pure internal logic operating on tool call records.

No findings.

## Tests (next-test-analyzer)

The reproduction test directly covers the bug scenario: a read-only `grep` command referencing a
dirty file produces no touched files and no scoped entries. The existing
`test_scope_git_files_to_current_turn_uses_only_turn_local_file_signals` test covers the positive
case (mutating commands DO extract paths). Together they form a complete behavioral boundary.

Test quality is good: `@pytest.mark.unit` marker present, descriptive name, asserts all three
relevant outputs (`touched_files`, `saw_mutation`, `scoped`).

No findings.

### Suggestions (non-blocking)

- **Parameterized read-only variants**: The test uses `grep` as the sole read-only example. A
  `@pytest.mark.parametrize` with `cat`, `git diff`, `head` would catch regressions from an
  overly broad future mutation pattern. Low urgency since one representative is sufficient.

- **Mixed-turn test**: A turn containing a read-only shell command AND a structured mutator (`edit`)
  would verify the read-only shell's paths are excluded while the mutator's are included. This is the
  most common real-world pattern (agents `grep` then `edit` in the same turn).

## Errors (next-silent-failure-hunter)

The fix does not introduce any new silent failure paths. The mutation classifier
(`_command_likely_mutates_files`) has known gaps (e.g., `dd`, `patch`, `curl -o`, `wget -O`),
but these are pre-existing and the downstream behavior is fail-closed — missed mutations result
in under-counting, not false positives.

No findings introduced by this fix.

### Suggestions (non-blocking)

- Add `logger.debug("Shell command classified as non-mutating: %.120s", command)` for debugging
  rejected commands. Low-cost, high-value for future investigation.

## Comments (next-comment-analyzer)

The existing comment on line 348 ("Shell tools can mutate files but usually expose only freeform
command text") remains accurate with the new behavior. No stale comments.

No findings.

## Logging

No logging changes needed. The fix is a control-flow reorder within an existing function.
The function's callers already log at appropriate levels.

No findings.

## Demo

Bug fix with no user-facing CLI/config/API changes. No demo artifact required.

Not applicable.

## Simplify

The change is already minimal — a 3-line reorder. No simplification opportunities.

No findings.

---

## Summary

| Severity   | Count |
| ---------- | ----- |
| Critical   | 0     |
| Important  | 0     |
| Suggestion | 3     |

**Verdict: APPROVE**

The fix is minimal, correct, and well-tested. It trades potential under-counting (fail-closed) for
the elimination of false-positive checkpoint attribution from read-only shell commands. The
reproduction test directly exercises the bug scenario. All review lanes executed with no Critical
or Important findings.
