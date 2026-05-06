---
id: 'software-development/procedure/lifecycle/prepare/discovery'
type: 'procedure'
domain: 'software-development'
scope: 'global'
description: 'Pair-based discovery phase. Both workers explore the problem independently, then discuss together and converge on requirements understanding.'
---

# Prepare Discovery — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Explore the problem, surface hidden assumptions, check against reality, resolve
unknowns, and converge on a shared understanding of what the requirements should be.

Discovery produces shared understanding, not artifacts. You will receive an explicit
write instruction with the exact command after convergence.

## Preconditions

1. The todo carries input — a brain dump, existing requirements, or any
   starting state. All are treated as input to the pair's exploration.
2. Slug is active (not icebox, not delivered).

## Steps

### 1. Read and ground

Read and internalize the problem space:

- `telec todo artifacts read {slug} input` (or whatever starting artifacts exist)
- any existing `telec todo artifacts read {slug} requirements-review-findings`
- `telec roadmap list` — for signal about project direction and adjacent work
- the relevant code paths and adjacent patterns (ground truth)
- local docs needed to understand the domain constraints

Apply the domain-context loading rule from the preparation artifact quality
policy: identify which specs the input touches and load them via
`telec docs index` and `telec docs get` before discussing.

Go idle when grounding is complete.

### 1b. Fix mode (when dispatched with "FIX MODE")

When the dispatch note starts with "FIX MODE", this is a targeted revision, not
a fresh exploration:

- Read the existing `telec todo artifacts read {slug} requirements` alongside the review findings.
- Discuss the findings together. Apply targeted fixes. Preserve unflagged content.
- Skip fresh exploration. Proceed directly to convergence (step 3).

### 2. Explore and surface

This is the core of discovery. Both workers explore the problem through their
natural lens. There are no assigned roles — both contribute freely.

What you are looking for:

- **Hidden assumptions** — things the input takes for granted that may not hold.
  The human who wrote the input has context you don't — but they also have blind
  spots. Surface what they didn't say.
- **Hidden implications** — what does this change actually touch? What breaks?
  What else needs to change? Check the codebase.
- **Unknowns** — questions the input raises but doesn't answer. These must be
  resolved during discovery, not deferred to the builder.
- **Scope boundaries** — what is in, what is out, and why. Check against the
  roadmap for adjacent work that overlaps or depends on this.
- **Feasibility** — does the proposed approach actually work given the current
  codebase and constraints?
- **Intelligence boundaries** — does the proposed approach put code where
  intelligence belongs? Per `principle/intelligence-boundaries`: any
  classifier, scorer, judge, evaluator, or auto-fixer on free-text content
  is suspect. If the design needs "the wire layer should detect X about
  agent output" or "the cartridge should grade artifact Y," that is almost
  always a briefing problem masquerading as a code problem. Surface it now —
  the right fix is a briefing change, not a planning task.

Challenge each other. One of you sees things the other doesn't — that is the
whole point of having two perspectives.

### 2b. Resolve unknowns

**Discovery owns resolving all unknowns.** A requirement that contains an
unanswered question is defective — it pushes the unknown to the builder.

Resolve each unknown using the appropriate method:

1. **Codebase investigation**: read the source, trace the call chain, verify
   behavior from code.
2. **Existing documentation**: check consolidated docs (`telec docs index`,
   `telec docs index --third-party`).
3. **Third-party research**: for external tools not yet documented, execute the
   third-party research procedure.
4. **Empirical testing**: when docs don't cover it, run the test and record
   findings.
5. **Blocker**: if unresolvable, report it to the orchestrator. Do not convert
   it into a build task.

### 3. Converge

Discovery ends when both workers agree on what the requirements should contain.
Convergence is not a formal vote — it is the natural end of the discussion
when both perspectives have been heard and tensions are resolved.

Use DOR gates 1-3 as the convergence bar: intent/success, scope/size, and
verification must all be satisfiable before discovery is done.

Do not split the todo here. Discovery owns requirements understanding, not
execution decomposition. If the work may be too large, express that in the
discussion so the draft phase can make the grounded split decision.

Go idle when converged.

## Outputs

None. Shared understanding through conversation.

## Recovery

1. If the pair partner fails to start, continue solo and note the missing
   second perspective to the orchestrator.
2. If convergence stalls, continue with explicit `[inferred]` markers rather
   than leaving requirements understanding half-formed.
3. If a major architectural decision cannot be grounded, report the blocker
   to the orchestrator.
