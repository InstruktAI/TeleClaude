# Implementation Plan: Delivery Verification Gates

## Overview

Implement completeness verification by updating existing prime-* and next-* command files. No shell scripts, no subprocess validation—pure command-level checks embedded in the workflow.

**Core mechanic:** Commands verify their own completeness before progressing. Workers stop when encountering out-of-scope work. Reviewers trace evidence. Orchestrators collaborate on deferrals.

---

## Phase 1: Builder Autonomy and Deferrals

**Goal:** Workers are pragmatic first, escalate with structure only when necessary.

### Task 1.1: Update prime-builder.md - Add autonomy section

**File:** `~/.agents/commands/prime-builder.md`
**Location:** After "Your Responsibilities" section (after line 17)

**Add this new section:**

```markdown
## Autonomy and Pragmatism

You are expected to be resourceful and pragmatic, NOT a rigid executor.

**When encountering scope questions:**

1. **First, look around:**
   - Check existing patterns in the codebase
   - Read relevant docs and architecture files
   - Examine similar implementations
   - Check if requirements give implicit guidance

2. **If you can reasonably infer the right approach:**
   - DO IT. Don't wait for permission.
   - Document your decision in implementation-plan.md notes
   - Move forward confidently

3. **Only escalate when:**
   - Multiple valid approaches exist with different trade-offs
   - Work is clearly outside the stated requirements scope
   - Decision requires architectural changes
   - You genuinely cannot determine the right path

**DO NOT mark tasks as "deferred" and continue.** Either:
- Solve it pragmatically in-line
- Create deferrals.md and STOP (see next-build.md for format)
```

- [x] Complete this task

---

### Task 1.2: Update next-build.md - Add deferral mechanism

**File:** `~/.agents/commands/next-build.md`
**Location:** After "Step 3: Execute Task Groups" section (after line 79)

**Add this new section:**

```markdown
## Step 3.5: Handling Out-of-Scope Work

If you encounter work that seems outside the current todo's scope:

### First: Can You Solve It Pragmatically?

Ask yourself:
- Is the approach obvious from existing patterns?
- Would any reasonable developer make the same choice?
- Is the work small enough to complete now (< 1 hour)?
- Does it directly serve the stated requirements?

**If YES to all:** Do it in-line. Add a note to the task in implementation-plan.md explaining your decision.

### If Genuinely Out-of-Scope: Create deferrals.md

**DO NOT mark tasks as "deferred" in implementation-plan.md and continue.**

Instead:

1. Create `todos/{slug}/deferrals.md` with this format:

```markdown
# Deferred Work Candidates

## [Item Title]

**Encountered during:** [Task name from implementation-plan.md]

**Description:** [What work was encountered, why it seems out-of-scope]

**Why deferral candidate:**
- [Reason 1: e.g., "Requirements don't specify cache invalidation strategy"]
- [Reason 2: e.g., "Multiple valid approaches with different trade-offs"]

**Estimated effort:** [e.g., "2-3 hours" or "Requires architecture decision"]

**Options:**
1. **Do now:** [Quick approach that works for current requirements]
2. **New todo:** [Describe what a separate todo would address]
3. **Descope:** [Why this might not be necessary]

**Status:** PENDING_ORCHESTRATOR_DECISION
```

2. **STOP work immediately**
3. Report to orchestrator: "Encountered out-of-scope work. Created deferrals.md. Awaiting decision."

**The orchestrator will:**
- Review your deferral
- Decide: do now, new todo, or descope
- Send you guidance to continue

**CRITICAL:** Do NOT mark build as complete if deferrals.md has PENDING items.
```

- [x] Complete this task

---

### Task 1.3: Update next-build.md - Add pre-completion checks

**File:** `~/.agents/commands/next-build.md`
**Location:** After "Step 5: Report Completion" section (before "Step 6: Commit")

**Add this new section:**

```markdown
## Step 5.5: Pre-Completion Checks

Before reporting completion, verify:

1. **All tasks checked:**
   ```bash
   # Check for unchecked boxes in implementation-plan.md
   grep -E "^[[:space:]]*-[[:space:]]*\[ \]" todos/{slug}/implementation-plan.md
   ```
   If any found: You're not done. Complete them or remove them.

2. **No silent deferrals (task lines only):**
   ```bash
   # Check for "deferred" keyword in task lines only (ignore instructional text/examples)
   grep -iE "^[[:space:]]*-[[:space:]]*\\[[ x]\\].*\\bdeferred\\b" todos/{slug}/implementation-plan.md
   ```
   If found: A task was marked "deferred" instead of creating deferrals.md. This is wrong.
   - Remove "deferred" from the task line
   - Create proper deferrals.md entry
   - STOP and report

3. **Check deferrals.md:**
   - If `todos/{slug}/deferrals.md` exists with PENDING items:
     - DO NOT report build complete
     - Report: "Build paused. Awaiting orchestrator decision on deferrals."

**Only report completion when:**
- All tasks `[x]`
- No "deferred" keywords in task lines
- No PENDING items in deferrals.md (or file doesn't exist)
```

- [x] Complete this task

---

## Phase 2: Reviewer Completeness Verification

**Goal:** Reviewers verify requirements are actually met with documented evidence.

### Task 2.1: Update prime-reviewer.md - Expand responsibilities

**File:** `~/.agents/commands/prime-reviewer.md`
**Location:** Replace "Your Responsibilities" section (lines 18-26)

**Replace with this:**

```markdown
## Your Responsibilities

1. **Verify completeness** - All requirements actually implemented (not just code exists)
2. **Evaluate against requirements** - Does the code do what was specified?
3. **Check code quality** - Follows patterns, directives, project conventions
4. **Assess test coverage** - Behavioral tests, edge cases, integration tests exist
5. **Inspect error handling** - No silent failures, proper logging
6. **Review documentation** - Comments accurate, not stale
7. **Produce structured findings** - Organized by severity with file:line refs
8. **Deliver verdict** - Binary decision, no hedging

**Completeness is your PRIMARY responsibility.** Code can be beautifully written but still incomplete.
```

- [x] Complete this task

---

### Task 2.2: Update prime-reviewer.md - Add completeness protocol

**File:** `~/.agents/commands/prime-reviewer.md`
**Location:** After "Verdict Criteria" section (after line 52)

**Add this new section:**

```markdown
## Completeness Verification Protocol

Before delivering any verdict, you MUST verify implementation completeness. This is NON-NEGOTIABLE.

### 1. Check Implementation Plan Completeness

```bash
grep -E "^[[:space:]]*-[[:space:]]*\[ \]" todos/{slug}/implementation-plan.md
```

**If unchecked tasks found:** Verdict = REQUEST CHANGES
- Finding: "Unchecked tasks remain in implementation-plan.md"
- These must be completed or removed

### 2. Check for Silent Deferrals (Task Lines Only)

```bash
# Only scan task list lines; ignore instructional text and examples.
grep -iE "^[[:space:]]*-[[:space:]]*\\[[ x]\\].*\\bdeferred\\b" todos/{slug}/implementation-plan.md
```

**If "deferred" keyword found:** Verdict = REQUEST CHANGES
- Finding: "Work marked as 'deferred' without proper deferrals.md"
- This indicates incomplete work masquerading as done

### 3. Check Deferrals Document

```bash
ls todos/{slug}/deferrals.md 2>/dev/null
```

**If deferrals.md exists:**
- Read the file
- Check each item's status
- **If ANY item has status PENDING_ORCHESTRATOR_DECISION:**
  - Verdict = BLOCK (do not write review-findings.md)
  - Report to orchestrator: "Deferrals exist. Orchestrator must resolve before review."

**If all deferrals are RESOLVED/MOVED_TO_TODO/DESCOPED:**
- Continue with review
- Verify resolutions are sensible

### 4. Trace Success Criteria Implementation

For EACH success criterion in `todos/{slug}/requirements.md`:

**4.1 Locate implementing code:**
- Find the specific function/method that implements this criterion
- If no implementing code exists → Finding: "Success criterion not implemented"

**4.2 Trace the call path:**
- Start from entry point (API handler, CLI command, event handler)
- Trace through to the implementing code
- Verify code is actually invoked in production paths
- If code exists but is never called → Finding: "Dead code - criterion not actually implemented"

**4.3 Verify test coverage:**
- Find at least one integration test that exercises this criterion end-to-end
- Verify the test uses real implementations (not over-mocked)
- Verify the test would FAIL if the criterion wasn't met
- If test only mocks behavior → Finding: "Test doesn't prove criterion works"

**4.4 Document your verification:**

In review-findings.md, add section:

```markdown
## Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| {criterion text} | {file:line} | {entry → ... → impl} | {test file:test name} | ✅/❌ |
```

**4.5 Verdict rule:**

- ALL criteria verified → Can APPROVE (if no other issues)
- ANY criterion unverified → MUST REQUEST CHANGES

### 5. Integration Test Verification

Verify at least ONE integration test exists that:
- Exercises the primary user-facing flow end-to-end
- Uses real implementations for core components (not mocked)
- Tests observable outcomes (database state, API responses, side effects)
- Would FAIL if the feature doesn't actually work

**If no such test exists:**
- Finding: "Missing integration test for main flow"
- Verdict = REQUEST CHANGES

### 6. Test Quality Check

Look for over-mocking anti-patterns:
- Tests that mock everything and only verify mocks were called
- Tests that test implementation details, not behavior
- Tests of isolated units with no integration tests

**If tests are over-mocked:**
- Finding: "Tests over-mocked - don't prove feature works"
- Suggest: "Add integration test that exercises real flow"
```

- [x] Complete this task

---

### Task 2.3: Update next-review.md - Add pre-review checks

**File:** `~/.agents/commands/next-review.md`
**Location:** After "## Step 4: Parallel Skill-Based Review" section (after line 70)

**Add this new section:**

```markdown
## Step 3.5: Pre-Review Completeness Checks

**BEFORE dispatching skill-based review, run these checks:**

### Check 1: Deferrals Block Review

```bash
if [ -f "todos/{slug}/deferrals.md" ]; then
  if grep -q "Status: PENDING_ORCHESTRATOR_DECISION" "todos/{slug}/deferrals.md"; then
    echo "BLOCKED: Deferrals pending orchestrator decision"
    exit 1
  fi
fi
```

**If deferrals are pending:**
- DO NOT proceed with review
- Report to orchestrator: "Review blocked. Deferrals must be resolved first."
- Orchestrator will handle deferrals, then re-dispatch review

### Check 2: Implementation Plan Complete

```bash
unchecked=$(grep -cE "^[[:space:]]*-[[:space:]]*\[ \]" "todos/{slug}/implementation-plan.md" || echo "0")
if [ "$unchecked" -gt 0 ]; then
  echo "WARNING: $unchecked unchecked tasks in implementation-plan.md"
fi
```

**If unchecked tasks found:**
- Continue review BUT add finding about unchecked tasks
- Verdict will be REQUEST CHANGES

### Check 3: Silent Deferrals Check (Task Lines Only)

```bash
if grep -qiE "^[[:space:]]*-[[:space:]]*\\[[ x]\\].*\\bdeferred\\b" "todos/{slug}/implementation-plan.md"; then
  echo "WARNING: 'deferred' keyword found in task lines of implementation-plan.md"
fi
```

**If "deferred" found:**
- Add critical finding: "Silent deferral detected"
- Verdict will be REQUEST CHANGES

**Only proceed to Step 4 (skill-based review) if deferrals.md is not blocking.**
```

- [x] Complete this task

---

### Task 2.4: Update next-review.md - Update findings template

**File:** `~/.agents/commands/next-review.md`
**Location:** In "## Step 5: Aggregate Findings" section (around line 77)

**Replace the "## Requirements Coverage" section with:**

```markdown
## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: {count} → {list if any}
- Silent deferrals found: {yes/no} → {details if yes}

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| {criterion from requirements.md} | {file:line or "NOT FOUND"} | {entry → impl or "NOT CALLED"} | {test file:name or "NO TEST"} | ✅/❌ |

**Verification notes:**
- [Notes about tracing, any concerns, assumptions made]

### Integration Test Check
- Main flow integration test exists: {yes/no}
- Test file: {file:name}
- Coverage: {what the test exercises}
- Quality: {uses real implementations / over-mocked}

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| {req} | ✅/⚠️/❌ | |
```

- [x] Complete this task

---

## Phase 3: Orchestrator Deferral Management

**Goal:** Orchestrator collaborates with worker to resolve deferrals.

### Task 3.1: Update prime-orchestrator.md - Add deferral handling

**File:** `~/.agents/commands/prime-orchestrator.md`
**Location:** After "## Your Responsibilities" section (after line 17)

**Add this new section:**

```markdown
## Handling Deferrals

When a worker creates `deferrals.md` with PENDING items, you must resolve them before work continues.

### Deferral Resolution Process

1. **Read deferrals.md** in the todo folder
2. **For each PENDING item, decide:**

   **Option A: Do it now**
   - It's actually in-scope and worker can handle it
   - Send message: "Complete [item] per option 1 in deferrals.md"
   - Worker updates deferrals.md status to RESOLVED
   - Worker continues build

   **Option B: Create new todo**
   - Work is genuinely out-of-scope for current todo
   - Add item to `todos/roadmap.md` with proper title/description
   - Update deferrals.md: change status to `MOVED_TO_TODO: {new-slug}`
   - Worker continues build

   **Option C: Descope**
   - Work is not actually necessary
   - Update `todos/{slug}/requirements.md` to clarify scope exclusion
   - Update deferrals.md: change status to `DESCOPED: {reason}`
   - Worker continues build

3. **Verify all items resolved:**
   - All deferrals.md items have status RESOLVED/MOVED_TO_TODO/DESCOPED
   - No PENDING items remain

4. **Resume worker:**
   - Send message: "All deferrals resolved. Continue with build."
   - Worker completes remaining tasks

### When Review is Blocked by Deferrals

If reviewer reports "Review blocked. Deferrals pending":

1. This means worker marked build complete but deferrals.md has PENDING items
2. This is a builder mistake (should have stopped and waited)
3. Resolve deferrals as above
4. Send worker back to build: "Resolve deferrals first, then mark build complete"
```

- [x] Complete this task

---

### Task 3.2: Update prime-orchestrator.md - Worker completion checks

**File:** `~/.agents/commands/prime-orchestrator.md`
**Location:** In "### When Notification Arrives (Worker Completed)" section (after line 63)

**Update point 1 to:**

```markdown
1. Look VERY carefully if their output matches our intended outcome:
   - Builders and code fixers are optimistic and often produce incomplete or incorrect work
   - Check for deferrals.md with PENDING items (means build is NOT actually complete)
   - Reviewers approving work frequently report IMPORTANT WORK to be marked as POST work, which should NOT happen
   - Check for unchecked tasks in implementation-plan.md
```

- [x] Complete this task

---

## Phase 4: Finalize Safety Net

**Goal:** Final sanity check before archiving to catch any missed issues.

### Task 4.1: Update next-finalize.md - Add final checks

**File:** `~/.agents/commands/next-finalize.md`
**Location:** Before "## Step 3: Final Tests" (insert after line 22)

**Add this new section:**

```markdown
## Step 2.5: Final Completeness Sanity Check

Before proceeding with finalize, do a final verification:

### Check 1: Review Approved

```bash
if ! grep -q "^\*\*\[x\] APPROVE\*\*" "trees/{slug}/todos/{slug}/review-findings.md"; then
  echo "ERROR: Review not approved"
  exit 1
fi
```

### Check 2: No Unchecked Tasks

```bash
if grep -qE "^[[:space:]]*-[[:space:]]*\[ \]" "trees/{slug}/todos/{slug}/implementation-plan.md"; then
  echo "ERROR: Unchecked tasks in implementation-plan.md"
  exit 1
fi
```

### Check 3: No Unchecked Success Criteria

```bash
if grep -qE "^[[:space:]]*-[[:space:]]*\[ \]" "trees/{slug}/todos/{slug}/requirements.md"; then
  echo "ERROR: Unchecked success criteria in requirements.md"
  exit 1
fi
```

### Check 4: No Pending Deferrals

```bash
if [ -f "trees/{slug}/todos/{slug}/deferrals.md" ]; then
  if grep -q "PENDING_ORCHESTRATOR_DECISION" "trees/{slug}/todos/{slug}/deferrals.md"; then
    echo "ERROR: Unresolved deferrals"
    exit 1
  fi
fi
```

**If ANY check fails:**
- DO NOT proceed with finalize
- Report to orchestrator: "Finalize blocked: {reason}"
- Orchestrator must investigate and resolve before finalize can proceed
```

- [x] Complete this task

---

## Testing Strategy

### Integration Tests (Manual)

**Test 1: Deferral flow end-to-end**
1. Create test todo: `todos/test-deferrals/`
2. Worker encounters ambiguous work → creates deferrals.md
3. Orchestrator resolves (do now) → worker completes
4. Reviewer verifies → approves
5. Finalize succeeds

**Test 2: Incomplete work blocked**
1. Create test todo with intentionally incomplete implementation
2. Worker reports complete with unchecked tasks → self-blocks
3. Fix tasks → worker reports complete
4. Reviewer traces success criteria → REQUEST CHANGES (one criterion unverified)
5. Fix missing implementation → re-review → APPROVE

**Test 3: Silent deferral caught**
1. Create test todo, manually add "deferred" to a task line (checkbox item) in implementation-plan.md
2. Worker pre-completion check catches it
3. Reviewer also catches it if worker misses
4. Must create proper deferrals.md or remove "deferred" from the task line

**Test 4: Autonomous problem-solving**
- Give worker todo with slight ambiguity
- Verify worker solves in-line pragmatically (doesn't create deferrals.md unnecessarily)

**Test 5: Proper escalation**
- Give worker clearly out-of-scope work
- Verify worker creates deferrals.md and stops

**Test 6: Evidence-based review**
- Create todo, verify reviewer documents code location, call path, test for each criterion
- Verify reviewer cannot APPROVE without complete evidence

---

## File Change Summary

| File | Changes |
|------|---------|
| `~/.agents/commands/prime-builder.md` | Add "Autonomy and Pragmatism" section |
| `~/.agents/commands/next-build.md` | Add "Handling Out-of-Scope Work" and "Pre-Completion Checks" sections |
| `~/.agents/commands/prime-reviewer.md` | Expand responsibilities, add completeness protocol |
| `~/.agents/commands/next-review.md` | Add pre-review checks, update findings template |
| `~/.agents/commands/prime-orchestrator.md` | Add deferral handling, update worker checks |
| `~/.agents/commands/next-finalize.md` | Add final sanity checks |

**No Python code changes. No shell scripts. Pure command prompt updates.**

---

## Implementation Order

1. **Phase 1** (Builder) - Set autonomy expectations, add deferral mechanism
2. **Phase 3** (Orchestrator) - Enable orchestrator to handle deferrals
3. **Phase 2** (Reviewer) - Add completeness verification after deferral flow works
4. **Phase 4** (Finalize) - Add safety net last

**Rationale:** Build the deferral communication channel first (builder creates, orchestrator resolves), then add verification (reviewer checks), then final safety (finalize catches misses).

---

## Rollout Strategy

1. **Phase 1 + 3 first** - Test deferral flow without blocking review
2. **Iterate based on real usage** - See how often deferrals are created
3. **Phase 2 + 4** - Add verification gates once deferral flow is stable
4. **Monitor** - Track how often incompleteness is caught at each phase

---

## Success Criteria from Requirements

- [x] prime-builder.md emphasizes autonomy and pragmatism
- [x] next-build.md defines deferrals.md format and pre-completion checks
- [x] prime-reviewer.md makes completeness PRIMARY responsibility
- [x] next-review.md blocks if deferrals PENDING, requires success criteria evidence
- [x] prime-orchestrator.md defines deferral resolution process
- [x] next-finalize.md has final sanity checks before archiving
- [x] Manual verification — silent deferral checks scan task lines only, instructional text excluded
- [x] Manual verification — reviewer guidance focuses on evidence, not AI prompt simulations
- [x] Manual verification — finalize sanity check references documented evidence paths
