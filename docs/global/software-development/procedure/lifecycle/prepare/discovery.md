---
id: 'software-development/procedure/lifecycle/prepare/discovery'
type: 'procedure'
domain: 'software-development'
scope: 'global'
description: 'Pair-based discovery phase. Both workers explore the problem together and converge before requirements are written.'
---

# Prepare Discovery — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

You are part of a pair. Both of you received the same input and are linked via
direct conversation. Your job is to explore the problem together — surface
hidden assumptions, check against reality, resolve unknowns, and converge on
what the requirements should be.

Discovery is pair-based. There are no roles during discovery. Both workers
contribute freely through their natural perspective. You discuss, challenge
each other, and converge. After convergence, the orchestrator assigns a writer
to record the agreed requirements.

This phase produces shared understanding. The writer records that understanding
as `requirements.md` after the pair converges.

## Preconditions

1. The todo carries input — a brain dump, existing requirements, or any
   starting state. All are treated as input to the pair's exploration.
2. You are linked to your pair partner via direct conversation.
3. `todos.db` roadmap is readable.
4. Slug is active (not icebox, not delivered).

## Steps

### 1. Read and ground — together

Both workers read the same material:

- `telec todo artifacts read {slug} input` (or whatever starting artifacts exist)
- any existing `telec todo artifacts read {slug} requirements-review-findings`
- `todos.db` roadmap — for signal about project direction and adjacent work
- the relevant code paths and adjacent patterns (ground truth)
- local docs needed to understand the domain constraints

Apply the domain-context loading rule from the preparation artifact quality
policy: identify which specs the input touches and load them before discussing.

### 1b. Fix mode (when dispatched with "FIX MODE")

When the dispatch note starts with "FIX MODE", this is a targeted revision, not
a fresh exploration:

- Read the existing `telec todo artifacts read {slug} requirements` alongside the review findings.
- Discuss the findings together. Apply targeted fixes. Preserve unflagged content.
- Skip fresh exploration. Proceed directly to the quality check (step 4) and
  write (step 5).

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

Discuss these via direct conversation. Challenge each other. One of you sees
things the other doesn't — that is the whole point of having two perspectives.

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
5. **Blocker**: if unresolvable, write it to `dor-report.md` as
   `needs_decision`. Do not convert it into a build task.

### 3. Converge

Discovery ends when both workers agree on what the requirements should be.
Convergence is not a formal vote — it is the natural end of the discussion
when both perspectives have been heard and tensions are resolved.

Use DOR gates 1-3 as the convergence bar: intent/success, scope/size, and
verification must all be satisfiable before discovery is done.

### 4. Requirements quality standard

The requirements the pair converged on must satisfy the preparation artifact
quality policy:

- **Completeness**: every intent from the input is captured or explicitly
  deferred.
- **Testability**: each requirement has a verification path.
- **Grounding**: verified against actual domain specs, not general knowledge.
- **Review-awareness**: DoD implications are reflected.
- **No implementation leakage**: requirements say what and why, not how.
- **Inferences marked**: anything inferred (not stated in the input) is marked
  `[inferred]`.
- **Unknowns resolved**: all questions answered with findings.

### 5. Write requirements

After the pair converges, the assigned writer records `requirements.md`:

- Grounded in the discovery findings and the pair's discussion.
- Structured per the quality standard above.
- Inferences marked explicitly.

Update `todos.db` state:

```yaml
grounding:
  valid: true
  base_sha: '<current HEAD>'
  input_digest: '<hash of input>'
  last_grounded_at: '<now ISO8601>'
  invalidation_reason: null
```

### 6. Review

The other pair member reviews what the writer recorded: did they capture
everything the pair discussed? Is anything missing or misrepresented?

If gaps are found, the writer corrects. When both agree the recording is
accurate, requirements are ready for human approval.

### 7. Enforce boundaries

- Do not split the todo here. Discovery owns requirements, not execution
  decomposition.
- Do not write `implementation-plan.md` here.
- If the work may be too large, express that in the requirements so the draft
  phase can make the grounded split decision.

## Outputs

1. `requirements.md` — grounded, review-aware, pair-agreed requirements.
2. `todos.db` state — grounding metadata updated.
3. Third-party doc snippets indexed (when research was needed).

## Recovery

1. If the pair partner fails to start, continue solo and note the missing
   second perspective in `dor-report.md`.
2. If convergence stalls, continue with explicit `[inferred]` markers rather
   than leaving requirements half-formed.
3. If a major architectural decision cannot be grounded, write the blocker to
   `dor-report.md`.
