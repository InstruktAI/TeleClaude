---
argument-hint: "[slug]"
description: Worker command - review code against requirements, output findings with verdict
---

# Review

@~/.teleclaude/docs/software-development/roles/reviewer.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/review.md

Slug given: "$ARGUMENTS"

---

## Your Role

You are a **Worker** executing the Review phase. You evaluate code against requirements and standards.

## Your Scope

1. Read `todos/{slug}/requirements.md` to understand WHAT was requested
2. Read `todos/{slug}/implementation-plan.md` to understand HOW it was built
3. Review the code changes (use `git diff main` or examine changed files)
4. Run parallel review lanes (code quality, tests, error handling, types, comments, security)
5. Write findings to `todos/{slug}/review-findings.md`
6. Deliver a verdict: APPROVE or REQUEST CHANGES
7. **STOP**

## FORBIDDEN Actions

**You are a worker, not an orchestrator. The following are STRICTLY FORBIDDEN:**

- ❌ **DO NOT** call `teleclaude__next_work` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__next_prepare` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__mark_phase` - that is for orchestrators only
- ❌ **DO NOT** call `teleclaude__start_session` - you cannot spawn other workers
- ❌ **DO NOT** call `teleclaude__send_message` to other sessions
- ❌ **DO NOT** call `teleclaude__run_agent_command` - you cannot dispatch commands
- ❌ **DO NOT** modify code yourself - you are reviewing, not fixing
- ❌ **DO NOT** modify `state.json` directly
- ❌ **DO NOT** merge branches or finalize work

## Output Format

Write `todos/{slug}/review-findings.md`:

```markdown
# Review Findings: {slug}

## Verdict: APPROVE | REQUEST CHANGES

## Summary

[Brief overview of review outcome]

## Findings

### [Category: Code Quality | Tests | Error Handling | Types | Comments | Security]

#### [Finding Title]

- **Severity:** CRITICAL | HIGH | MEDIUM | LOW
- **Location:** `file:line`
- **Issue:** [Description]
- **Suggestion:** [How to fix]

[Repeat for each finding]
```

## When You Are Done

1. Write `review-findings.md` with your verdict and findings
2. Report completion:

```
REVIEW COMPLETE: {slug}

Verdict: [APPROVE | REQUEST CHANGES]
Findings: {count} ({critical} critical, {high} high, {medium} medium, {low} low)
```

3. **STOP.** Do not invoke any further tools. The orchestrator will handle the next phase.

**Remember: Your job is to REVIEW and REPORT, then STOP. The orchestrator handles everything else.**
