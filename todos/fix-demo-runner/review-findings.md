# Review Findings: fix-demo-runner

## Review Scope

Branch: `fix-demo-runner`
Base: `main` (merge-base)
Changed files: 18
Review lanes: code, tests, docs

## Critical

None.

## Important

None.

## Suggestions

### 1. Semver gate docs are imprecise for demo.md path

**Location:** `docs/global/software-development/procedure/lifecycle/demo.md:101`, `docs/global/software-development/procedure/lifecycle-overview.md:64`, `docs/project/spec/demo-artifact.md:72`

All three docs state "Breaking major version bumps disable stale demos automatically via semver gate." The semver gate at `telec.py:1336-1345` only applies to the **fallback path** (legacy `demo` field from `snapshot.json`). The demo.md path at `telec.py:1276-1320` runs validation directly without version checking. This is correct behavior — demo.md blocks that reference removed APIs will fail on execution, which is the right outcome — but the blanket documentation statement could be more precise.

### 2. Skip-validation regex requires non-empty reason

**Location:** `teleclaude/cli/telec.py:1148`

The regex `r"<!--\s*skip-validation:\s*(.+?)\s*-->"` uses `.+?` which requires at least one character for the reason. `<!-- skip-validation: -->` (empty reason) won't match, and the block will execute instead of being skipped. The convention requires a reason, so this is defensive behavior — but it fails silently rather than warning. Low risk since the safer failure mode (executing the block) is the outcome.

### 3. Test gap: all-blocks-skipped path

**Location:** `tests/unit/test_next_machine_demo.py`

No test covers the case where all code blocks in a demo.md are annotated with `<!-- skip-validation: reason -->`. The code path at `telec.py:1295-1297` ("All code blocks skipped. Demo has guided steps only.") is untested. 12-line test, low risk.

### 4. Pre-existing: snapshot.json schema field names don't match existing artifacts

**Location:** `docs/project/spec/demo-artifact.md:44-45`

The schema documents `"delivered"` and `"commit"` but all existing artifacts use `"delivered_date"` and `"merge_commit"`. The code handles both via fallback (`snapshot.get("delivered_date", snapshot.get("delivered", ""))`). Not introduced by this branch — the diff only removed the `demo` field from the schema. The Known Caveats section partially addresses this.

### 5. Pre-existing: `delivered.md` vs `delivered.yaml` in quality-checklist template

**Location:** `templates/todos/quality-checklist.md:38`

The Finalize Gates section says "Delivery logged in `todos/delivered.md`" but the actual file is `todos/delivered.yaml`. Pre-existing error in a file modified by this branch.

## Positive Observations

- Implementation is clean and well-structured. The `_extract_demo_blocks` function is a focused utility with clear responsibilities.
- Test coverage is good: extraction edge cases (empty, non-bash, skip-validation, multiple blocks), CLI runner paths (demo.md preferred, todos fallback, guided-only, failure), and scaffold integration.
- Backward compatibility is properly implemented — fallback to snapshot.json `demo` field when no demo.md exists.
- Documentation is internally consistent across 9 changed doc files. The lifecycle (prepare draft → build gate → post-delivery presentation) is described consistently.
- No stale references to the old system (demo.sh, widget, celebration-widget) remain.
- The venv PATH prepending at `telec.py:1299-1304` is correct and documented in the spec.

## Verdict

**APPROVE**

All requirements implemented. All implementation plan tasks checked. Build gates fully checked. No critical or important issues. The five suggestions are either pre-existing issues, minor doc precision improvements, or low-risk test gaps — none warrant REQUEST CHANGES.
