# Review Findings: next-demo

**Review round:** 2
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-21
**Verdict:** APPROVE

---

## R1 Finding Resolution

| ID    | Severity   | Status   | Summary                                                                      |
| ----- | ---------- | -------- | ---------------------------------------------------------------------------- |
| R1-F1 | Critical   | Resolved | Index YAML paths reverted to canonical project root                          |
| R1-F2 | Critical   | Resolved | Git metrics changed to `main~1..main` for post-merge accuracy                |
| R1-F3 | Important  | Resolved | Demo dispatch now uses `subfolder="trees/{args}"`                            |
| R1-F4 | Important  | Accepted | Recovery bullets remain inline (see R2-S1)                                   |
| R1-F5 | Important  | Resolved | Edge case tests added for missing pyproject.toml and missing snapshot.json   |
| R1-F6 | Suggestion | Accepted | Spec gap acceptable for initial delivery (see R2-S2)                         |
| R1-F7 | Suggestion | Accepted | Single required read is sufficient; agent loads spec via procedure reference |
| R1-F8 | Suggestion | Accepted | Path normalization is harmless and improves portability                      |

Both critical findings are fully resolved. The `main~1..main` approach correctly captures merge-introduced changes. The worktree subfolder fix ensures the demo agent runs from the right directory.

---

## Suggestions

### R2-S1: Recovery instructions still inline in command artifact

**File:** `agents/commands/next-demo.md:59-60`

Lines 59-60 contain recovery instructions as loose bullets after the Steps section rather than in a dedicated `## Recovery` section. Other commands use `## Recovery`. This is a pattern inconsistency but does not affect behavior — the instructions are present and clear. Acceptable as a follow-up cleanup.

### R2-S2: Demo spec could document pyproject.toml directory walk

**File:** `docs/project/spec/demo-artifact.md:55`

The spec says "Reads the current project version from pyproject.toml" without specifying the walk-up behavior. The generated demo.sh traverses parent directories to find pyproject.toml, falling back to `0.0.0`. This behavior is now tested (`test_demo_sh_missing_pyproject_fallback`) but not documented in the spec. Low risk — the test is the authoritative contract.

---

## Fix commit verification

Four fix commits since R1 baseline (`cda4aecd`):

1. `eca618f9` — Reverted index.yaml paths (R1-F1) ✅
2. `e0f00606` — Changed git metrics to `main~1..main` (R1-F2) ✅
3. `967212ca` — Changed subfolder to `trees/{args}` (R1-F3) ✅
4. `22e9bdc1` — Added edge case tests (R1-F5) ✅

All fixes are minimal and scoped to the reported findings. No regressions introduced.

---

## Build section validation

- [x] All implementation-plan task checkboxes are `[x]`
- [x] Build gates in quality-checklist.md are all checked
- [x] No deferrals.md exists (none to validate)
- [x] Fix commits address R1 critical and important findings

---

## Verdict: APPROVE

Both critical findings resolved. Important findings resolved or accepted with documented rationale. Remaining suggestions are low-risk improvements suitable for follow-up work. The demo feature is functionally complete, correctly wired into the state machine, and well-tested.
