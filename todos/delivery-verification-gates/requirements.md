# Delivery Verification Gates - Requirements

## Problem Statement

Work items are marked "delivered" despite incomplete implementation. This happens because:

1. **Silent deferrals**: Builders mark tasks as "deferred" in implementation plans and continue
2. **Success criteria ignored**: Requirements define criteria that reviewers never verify
3. **Tests don't prove functionality**: Unit tests mock too much, integration tests missing
4. **Review checks quality, not completeness**: Reviewers approve well-written incomplete code

**Root cause:** Each phase does its narrow job correctly, but nobody owns "is this actually complete?"

---

## Core Objectives

1. **Workers must be autonomous first** - solve problems pragmatically before escalating
2. **No silent deferrals** - if work seems out-of-scope, create deferrals.md and STOP
3. **Evidence-based verification** - reviewers must trace that success criteria are actually implemented
4. **Orchestrator handles deferrals** - collaborate with worker to decide: do now, new todo, or descope
5. **Integration tests required** - at least one test exercising the main user flow

---

## Architecture Overview

**No shell scripts. No subprocess validation. Pure command-level verification.**

Changes are made to existing prime-* and next-* command files to embed completeness checks into the workflow itself.

### The Deferral Flow

```
1. Builder encounters out-of-scope work
   ↓
2. Builder tries pragmatic in-line solution first
   ↓
3. If genuinely out-of-scope:
   - Create todos/{slug}/deferrals.md with PENDING items
   - STOP work, report to orchestrator
   ↓
4. Orchestrator reads deferrals.md, decides for each:
   - Do now: send worker back with guidance
   - New todo: add to roadmap, update deferrals.md to MOVED_TO_TODO
   - Descope: update requirements.md, mark deferral DESCOPED
   ↓
5. Worker continues after all deferrals RESOLVED
   ↓
6. Reviewer checks: deferrals.md has no PENDING items
7. Reviewer verifies: all success criteria implemented with evidence
```

---

## Command Changes Required

See `command-changes-analysis.md` for complete specifications. Summary:

### 1. prime-builder.md
**Change:** Add "Autonomy and Pragmatism" section
**Why:** Set expectation that workers solve problems in-line when reasonable, only escalate when truly necessary

### 2. next-build.md
**Changes:**
- Add "Handling Out-of-Scope Work" section with deferrals.md format
- Add "Pre-Completion Checks" to verify no unchecked tasks, no "deferred" keywords in task lines, no PENDING deferrals

**Why:** Workers catch incompleteness before reporting success

### 3. prime-reviewer.md
**Change:** Expand responsibilities to emphasize completeness verification as PRIMARY duty
**Why:** Reviewers understand their job is proving requirements are met, not just checking code quality

### 4. next-review.md
**Changes:**
- Add "Pre-Review Completeness Checks" to block review if deferrals are PENDING
- Add "Completeness Verification Protocol" with success criteria tracing template
- Update review-findings.md template to include evidence (code location, call path, test)

**Why:** Reviewers must document evidence that success criteria are implemented

### 5. prime-orchestrator.md
**Changes:**
- Add "Handling Deferrals" section with resolution process
- Update worker completion checks to look for deferrals.md with PENDING items

**Why:** Orchestrator has explicit process to handle deferrals collaboratively

### 6. next-finalize.md
**Change:** Add "Final Completeness Sanity Check" before merging
**Why:** Final safety net catches any missed issues before archiving

---

## Deferrals Document Format

**Location:** `todos/{slug}/deferrals.md`

**Created by:** Builder when encountering out-of-scope work

**Format:**

```markdown
# Deferred Work Candidates

## [Item Title]

**Encountered during:** [Task name from implementation-plan.md]

**Description:** [What work was encountered, why it seems out-of-scope]

**Why deferral candidate:**
- [Reason 1]
- [Reason 2]

**Estimated effort:** [e.g., "2-3 hours" or "Requires architecture decision"]

**Options:**
1. **Do now:** [Quick approach]
2. **New todo:** [What separate todo would address]
3. **Descope:** [Why might not be necessary]

**Status:** PENDING_ORCHESTRATOR_DECISION | RESOLVED | MOVED_TO_TODO: {slug} | DESCOPED: {reason}
```

---

## Success Criteria Verification Protocol

**Reviewer responsibility - performed during review phase**

For EACH success criterion in requirements.md:

### 1. Locate implementing code
- Find specific function/method implementing this criterion
- **If not found:** Mark unverified → REQUEST CHANGES

### 2. Trace call path
- Start from entry point (API handler, CLI command, event handler)
- Trace to implementing code
- Verify code is invoked in production paths
- **If exists but never called:** Mark unverified → REQUEST CHANGES

### 3. Verify test coverage
- Find integration test that exercises this criterion end-to-end
- Verify test uses real implementations (not over-mocked)
- Verify test would FAIL if criterion not met
- **If test only mocks:** Mark unverified → REQUEST CHANGES

### 4. Document evidence
In review-findings.md:

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| {text} | file:line | entry → impl | test:name | ✅/❌ |

### 5. Verdict rule
- ALL criteria verified → can APPROVE
- ANY criterion unverified → MUST REQUEST CHANGES

---

## Integration Test Requirement

Every work item MUST have at least ONE integration test that:
- Exercises the primary user-facing flow end-to-end
- Uses real implementations for core components (not mocked)
- Tests observable outcomes (DB state, API responses, side effects)
- Would FAIL if feature doesn't work

**If missing:** Reviewer adds finding, verdict = REQUEST CHANGES

---

## Completeness Checks Matrix

| Phase | Who | What Checked | Action if Incomplete |
|-------|-----|--------------|---------------------|
| Build completion | Builder (self-check) | All tasks `[x]`, no "deferred" in task lines, no PENDING deferrals | Don't report complete, create deferrals.md or finish tasks |
| Review start | Reviewer | deferrals.md has no PENDING items | Block review, report to orchestrator |
| Review evaluation | Reviewer | Success criteria traced with evidence, integration test exists | Add findings, REQUEST CHANGES |
| Finalize | Finalize worker | Review approved, no unchecked tasks/criteria, no PENDING deferrals | Block finalize, report to orchestrator |

---

## Autonomy Philosophy

**We want smart, pragmatic workers, not rigid executors.**

Workers should:
- Look around at existing patterns
- Make reasonable inferences from context
- Solve problems in-line when the approach is obvious
- Document pragmatic decisions

Workers should NOT:
- Wait for permission on trivial decisions
- Create deferrals for every small uncertainty
- Blindly follow requirements when context gives clear guidance

**Escalate only when:**
- Multiple valid approaches with different trade-offs
- Work clearly outside stated requirements scope
- Requires architectural decision
- Genuinely unclear what the right approach is

---

## What This Does NOT Do

1. **No tracking of deferred work** - Work is either done, explicitly deferred for decision (deferrals.md), or descoped
2. **No escape hatch for "deferred" keyword** - It should not appear in implementation-plan.md task lines. Instructional text and examples are allowed.
3. **No shell scripts** - All verification embedded in command prompts
4. **No subprocess calls** - Commands check their own completeness

---

## Success Criteria

Implementation complete when:

- [ ] prime-builder.md emphasizes autonomy and pragmatism
- [ ] next-build.md defines deferrals.md format and pre-completion checks
- [ ] prime-reviewer.md makes completeness PRIMARY responsibility
- [ ] next-review.md blocks if deferrals PENDING, requires success criteria evidence
- [ ] prime-orchestrator.md defines deferral resolution process
- [ ] next-finalize.md has final sanity checks before archiving
- [ ] Test run: worker creates deferrals.md, orchestrator resolves, reviewer verifies completeness
- [ ] Test run: incomplete work is caught and blocked at review
- [ ] Test run: finalize catches any missed issues before archiving

---

## Non-Goals

- Building a tracking system for deferred work across projects
- Creating elaborate prompts to prevent AI from gaming the system
- Adding bureaucratic overhead that slows down autonomous work
- Replacing human judgment with rigid automation
