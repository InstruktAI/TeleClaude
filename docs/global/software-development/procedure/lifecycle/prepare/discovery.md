---
id: 'software-development/procedure/lifecycle/prepare/discovery'
type: 'procedure'
domain: 'software-development'
scope: 'global'
description: 'Requirements discovery phase for next-prepare. Produces requirements from input using solo or triangulated discovery.'
---

# Prepare Discovery — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Derive `requirements.md` from `input.md`, codebase grounding, and applicable
documentation. Discovery may run either:

- **solo** when one architect already has enough grounding to write trustworthy
  requirements, or
- **triangulated** when the input still carries substantial ambiguity, hidden
  assumptions, or unresolved architectural tension.

This phase produces requirements only. Implementation planning and todo breakdown
belong to the later draft phase.

## Preconditions

1. `telec todo artifacts read {slug} input` exists with human thinking to derive from.
2. The discovery worker knows its own agent type and can select a complementary
   partner if triangulation is needed.
3. `todos.db` roadmap is readable.
4. Slug is active (not icebox, not delivered).

## Steps

### 1. Read and ground

Read:

- `telec todo artifacts read {slug} input`
- any existing `telec todo artifacts read {slug} requirements-review-findings`
- `todos.db` roadmap
- the relevant code paths and adjacent patterns
- local docs needed to understand the domain constraints

Apply the domain-context loading rule from the preparation artifact quality
policy: identify which specs the input touches and load them before writing
requirements. Domain specs are the ground truth — grounding, leakage detection,
and review-awareness cannot be evaluated without them.

### 1b. Fix mode (when dispatched with "FIX MODE")

When the dispatch note starts with "FIX MODE", this is a targeted revision, not a
fresh derivation:

- Read the existing `telec todo artifacts read {slug} requirements` alongside the review findings.
- Apply targeted fixes to address each finding. Preserve all unflagged content.
- Do not re-derive from scratch — the existing requirements were already grounded.
- Skip strategy selection (step 2) and triangulation (step 3); proceed directly to
  the quality standard check (step 4) and write the updated requirements (step 5).

### 1c. Execute third-party research (when input contains unknowns)

Scan `input.md` for questions about third-party tool behavior, API semantics,
flag combinations, or external system capabilities. These are research questions
— they ask "how does X work?" or "does X support Y?" about tools outside the
project's control.

**Discovery owns answering these questions, not deferring them.** A requirement
that lists unanswered research questions is defective — it pushes unknowns to the
builder, who will discover them at build time when the cost of rework is highest.

When research questions are found:

1. Check consolidated third-party docs first: `telec docs index --third-party`.
   If a doc already covers the question, load it and extract the answer.
2. If not covered, execute the third-party research procedure: search
   authoritative sources (official docs, vendor references), fetch, extract
   actionable facts, and index findings as a third-party doc snippet.
3. If empirical testing is required (flag combinations, runtime behavior that
   docs don't cover), run the test in a throwaway session and record the
   findings. Document what was tested, what was observed, and what the
   implications are for the requirements.
4. If a research question cannot be answered (no docs, no way to test), that is
   a blocker — write it to `dor-report.md` as a `needs_decision` item. Do not
   convert it into a build-phase task. Unanswered research is a preparation
   blocker, not a build task.

Only after all research questions are answered (or explicitly blocked) should
the worker proceed to writing requirements. Requirements must reference the
research findings, not restate the questions.

### 2. Choose discovery strategy

Decide how requirements should be produced:

- Use **solo discovery** when the input is concrete enough that one grounded
  architect can derive trustworthy requirements without burning extra cycles.
- Use **triangulated discovery** when a second perspective is still needed to
  expose hidden assumptions, missing constraints, or unresolved tensions.

If triangulation is needed, the discovery worker spawns the complementary agent
and converges with it before writing requirements.

### 3. Triangulate only when needed

When triangulation is chosen:

- split research between codebase grounding and domain/intent grounding
- compare findings directly
- resolve tensions before writing requirements

Use DOR gates 1-3 as the convergence bar: intent/success, scope/size, and
verification must all be satisfiable before discovery is done.

### 4. Requirements quality standard

The converged `requirements.md` must satisfy all rules from the preparation
artifact quality policy. In particular:

- **Completeness**: every intent expressed in `input.md` is captured as a
  concrete requirement or explicitly deferred with justification.
- **Testability**: each requirement has a verification path (test, observable
  behavior, or measurable outcome). "Works correctly" is not testable.
- **Grounding**: verify against the domain specs loaded in step 1, not against
  general knowledge. Requirements that reference non-existent APIs, wrong schema
  fields, or incorrect conventions are defective.
- **Review-awareness**: apply the DoD-driven review-awareness rule from the
  preparation artifact quality policy. Walk each DoD section and verify that the
  requirements reflect the implications.
- **No implementation leakage**: apply the implementation leakage rule from the
  preparation artifact quality policy. Use the concrete signals and discriminator
  test to identify leakage.
- **Inferences marked**: anything inferred from codebase or docs rather than
  explicitly stated in `input.md` is marked `[inferred]`. The human can
  correct inferences without searching for them.
- **Research resolved**: every third-party research question from `input.md` is
  answered with indexed findings, not restated as a requirement. A requirement
  that says "empirical testing required" or "research needed to determine X" is
  a defect — it means discovery deferred its own job to the builder. DOR gate 5
  (research complete) is enforced here, not at the gate phase.

### 5. Write requirements

Write `requirements.md`:

- Grounded in the discovery findings.
- Structured per the quality standard above.
- Inferences marked explicitly.

Update `todos.db` state:

```yaml
grounding:
  valid: true
  base_sha: '<current HEAD>'
  input_digest: '<hash of input.md>'
  last_grounded_at: '<now ISO8601>'
  invalidation_reason: null
```

### 6. Enforce boundaries

- Do not split the todo here. Discovery owns requirements, not execution
  decomposition.
- Do not write `implementation-plan.md` here.
- If you believe the work may be too large, express that in the requirements so
  the draft phase can make the grounded split/no-split decision.

### 7. Cleanup

If triangulation was used, end the partner session when convergence is done.

## Outputs

1. `telec todo artifacts read {slug} requirements` — grounded, review-aware requirements.
2. `todos.db` state — grounding metadata updated.
3. Third-party doc snippets indexed (when research was executed in step 1c).
4. Partner session ended after convergence when triangulation was used.

## Recovery

1. If a triangulation partner fails to start, continue solo and note the missing
   second perspective in `dor-report.md` if it materially reduces confidence.
2. If convergence stalls, continue solo with explicit `[inferred]` markers where
   needed rather than leaving requirements half-formed.
3. If discovery still cannot ground a major architectural decision, write the
   blocker clearly to `dor-report.md`.
