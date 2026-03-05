# Review Findings: context-delivery-dedup

## Review Scope

Diff: `f61d6a24..HEAD` (11 commits, 20 files changed)

Core change: `teleclaude/context_selector.py` lines 738, 742-743 — stop auto-expanding dependency
snippet content inline; list dep IDs in a `# Required reads (not loaded)` header instead.

Supporting changes: doc source trimming (baseline.md, baseline-progressive.md, telec-cli.md),
policy update (context-retrieval.md), validator fix (resource_validation.py), test alignment
(guardrail isolation, sync fixture schemas, resource_validation assertion targets).

## Critical

### C1: Demo artifact uses snippet with no dependencies — fabricated expected output

**Location:** `demos/context-delivery-dedup/demo.md`, block 1

The first executable block runs:
```bash
telec docs get general/policy/context-retrieval
# Expected: Header shows: # Required reads (not loaded): <dep-ids>
```

`general/policy/context-retrieval` has **no `## Required reads` section** — it has zero dependencies.
The `# Required reads (not loaded)` header will never appear for this snippet. The expected output
is fabricated and would fail in practice.

The demo's primary purpose is to demonstrate the dedup behavior, but its lead example exercises
a snippet that does not trigger the feature.

**Fix:** Use a snippet that actually has required reads dependencies. Many global snippets qualify
(e.g., `software-development/procedure/lifecycle/review`, `general/procedure/peer-discussion`,
`general/procedure/gathering`).

## Important

### I1: Missing test — requesting both a snippet and its dependency in one call

**Location:** `tests/unit/test_context_selector.py`

The primary agent workflow is: (1) call `telec docs get snippet-a`, see `# Required reads (not loaded): snippet-c`
in the header, (2) call `telec docs get snippet-a snippet-c` to get both. No test verifies this case.

Expected behavior: both contents appear, no `# Required reads (not loaded)` header emitted.

The code path (lines 731-732) should handle this correctly — `dep_ids` would be empty when both are in
`requested_set` — but the contract is untested. A regression here would silently break the primary
dedup workflow.

### I2: Pre-existing silent exception in `_resolve_requires` now impacts header accuracy

**Location:** `teleclaude/context_selector.py:447-450`

```python
try:
    content = current.path.read_text(encoding="utf-8")
except Exception:
    continue
```

Pre-existing bare `except Exception` with zero logging. If a snippet file can't be read, its
transitive dependencies are silently dropped from the resolved set. Before this change, this caused
silently missing expanded content. After this change, it causes silently missing dep IDs in the
`# Required reads (not loaded)` header — the agent won't know to fetch them.

This is pre-existing, but the new feature makes the impact worse: before, the agent got partial
content; now, the agent gets zero signal that the dependency exists. Adding `logger.warning` at
this site would surface the failure.

### I3: Success criteria SC4 not met — CLAUDE.md is 39.8k chars vs 28k target

The builder notes this is caused by unrelated `fix(docs)` commits that added Required/Scope/
Enforcement/Exceptions sections to many snippets (~12k inflation). The three targeted removals
did achieve their goal (~11k reduction from ~51k to ~40k).

The success criteria should be updated to reflect reality or a follow-up task created for further
trimming.

## Suggestions

### S1: Pre-existing `_load_baseline_ids` silent exception (line 352-355)

Same pattern as I2 — bare `except Exception: return set()` with no logging. If the baseline file
can't be read, `telec docs index --baseline-only` returns an empty index with no error. Not introduced
by this change, but worth a follow-up.

### S2: Snippet read failure not surfaced inline in output (line 752-754)

Pre-existing: when a requested snippet fails to load, the error is logged but the output contains
no inline marker. The agent sees `# Requested: snippet-a, snippet-b` but only gets snippet-a's
content with no explanation. An inline `# ERROR: Failed to read snippet-b` would make failures
visible to the agent.

### S3: Missing tests for multiple dependencies and transitive dependencies

The fixture tests a single dependency chain (A→C). No test verifies:
- Multiple deps in the header (A requires both C and D)
- Transitive deps (A→C→D, both C and D listed in header)

These code paths are straightforward (list comprehension + stack traversal), so risk is low.

## Paradigm-Fit Assessment

- **Data flow:** Change follows the established data layer. `build_context_output()` is the correct
  function; the change is a 4-line surgical edit to the output rendering loop.
- **Component reuse:** No copy-paste. The shared `_setup_dep_fixture` in tests is well-factored.
- **Pattern consistency:** Output format, function signature, and error handling patterns are
  consistent with surrounding code. The `resource_validation.py` fix correctly handles the new
  prose-only baseline file format with a justified comment.

## Principle Violation Hunt

- **Fallback/silent degradation:** No new unjustified fallbacks introduced. The `continue` at
  line 743 is intentional filtering (deps listed in header), not a silent fallback. Pre-existing
  silent exception patterns (I2, S1, S2) are noted but not introduced by this change.
- **DIP:** No violations — change stays within core module, no adapter imports.
- **SRP:** Function responsibility unchanged.
- **YAGNI/KISS:** Change is minimal and earned. No premature abstractions.
- **Coupling/Demeter:** No new coupling introduced.
- **Encapsulation/Immutability:** No violations.

## Requirements Trace

| Success Criteria | Status | Evidence |
|---|---|---|
| SC1: deps as IDs in header | PASS | Test `test_dep_not_expanded_inline_but_listed_in_header` |
| SC2: subsequent calls list deps | PASS | Each call computes deps independently |
| SC3: explicit fetch returns content | PASS | Test `test_explicit_dep_request_returns_content` |
| SC4: CLAUDE.md under 28k | FAIL | 39.8k — see I3 |
| SC5: Agent Direct Conversation on-demand | PASS | `grep -c` returns 0 in generated CLAUDE.md |
| SC6: `telec sessions -h` works at runtime | PASS | CLI help unaffected |
| SC7: All existing tests pass | PASS | Builder checklist confirmed |
| SC8: `telec sync` regenerates correctly | PASS | Builder checklist confirmed |

## Why No Zero-Finding Note

This review produced 1 Critical, 3 Important, and 3 Suggestion findings.

## Verdict

**REQUEST CHANGES**

The Critical demo finding (C1) must be fixed — the demo's lead block exercises a snippet with no
dependencies, making the expected output fabricated. The Important test gap (I1) should be addressed
to cover the primary agent dedup workflow.

I2 and I3 are pre-existing or external-cause issues that can be tracked as follow-ups rather than
blocking this delivery.
