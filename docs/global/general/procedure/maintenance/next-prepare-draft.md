---
id: 'general/procedure/maintenance/next-prepare-draft'
type: 'procedure'
scope: 'global'
description: 'Plan drafting phase for next-prepare. Produces implementation plans from approved requirements and splits the work when planning shows it is not atomic.'
---

# Next Prepare Plan Draft — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md

## Goal

Produce `implementation-plan.md` from approved `requirements.md`, or split the todo into
dependent child work items when planning shows the work is not atomic. This is a
single-agent phase — requirements derivation is handled earlier in discovery, not here.

The plan must be detailed enough for a builder to execute without guessing, and
review-aware enough that the reviewer finds no surprises. If that bar cannot be met
for one builder session, this phase owns the split.

## Preconditions

1. `todos/{slug}/requirements.md` exists and is approved (review verdict in state.yaml).
2. `todos/roadmap.yaml` is readable.
3. Slug is active (not icebox, not delivered).

## Steps

### 1. Read and ground

Read the full context before writing anything:

- `todos/{slug}/requirements.md` — the approved requirements.
- `todos/{slug}/input.md` — the original human thinking (for intent).
- The codebase: files that will be affected, adjacent patterns, existing implementations
  of similar functionality. Use `telec docs index` for relevant policies and specs.
- Definition of Done — every plan task must produce output that satisfies DoD gates.

### 1b. Fix mode (when dispatched with "FIX MODE")

When the dispatch note starts with "FIX MODE", this is a targeted revision, not a
fresh draft:

- Read the existing `todos/{slug}/implementation-plan.md` alongside the review findings.
- Apply targeted fixes to address each finding. Preserve all unflagged content.
- Do not re-draft from scratch — the existing plan was already grounded and approved.
- Skip the atomicity decision (step 2); proceed directly to updating the plan tasks
  affected by findings, then write the updated artifacts (step 5).

### 2. Decide whether the todo is atomic

Ground in the code before deciding whether to split. Use the DOR scope/size rules:

- estimate likely change volume from the real code paths, not from the prose alone
- decide whether the work is one coherent builder behavior or multiple independently
  shippable pieces
- account for verification and coordination cost, not just file count

If the work is too large for one builder session:

- create focused child todos
- seed them from the approved parent requirements
- add dependency ordering in `todos/roadmap.yaml`
- update the holder `todos/{slug}/state.yaml` `breakdown.todos`
- stop treating the parent as directly builder-ready

If the work is atomic, continue to plan drafting.

### 3. Draft the implementation plan

Structure the plan as an ordered task list. Each task must include:

- **What**: the concrete change (file, function, component).
- **Why**: the rationale for the approach. This prevents the builder from taking shortcuts.
  If the plan says "use adapter pattern" but doesn't say why, the builder may inline the
  logic instead. The "why" is the guard against drift.
- **Verification**: how the builder confirms the task is done (test to write, behavior to
  observe, lint to pass).
- **Referenced files**: exact file paths that will be created or modified. These are
  extracted into `state.yaml.grounding.referenced_paths` for staleness detection.

### 4. Anticipate review lanes

The plan must pre-satisfy what the reviewer will check. For each requirement:

- If it implies new behavior: plan includes corresponding test tasks.
- If it touches CLI: plan includes help text update task.
- If it introduces config surface: plan includes config wizard, sample, and spec update tasks.
- If it touches security boundaries: plan includes input validation and auth check tasks.
- If it introduces new code paths: plan states which patterns to follow and why.

A plan that does not anticipate review lanes will produce review findings that cost
more to fix than they cost to prevent.

### 5. Write artifacts

If the todo stays atomic, write:

- `todos/{slug}/implementation-plan.md` — the full plan with tasks, rationale, and verification.
- `todos/{slug}/demo.md` — draft demonstration plan: what medium (CLI, TUI, web, API),
  what the user observes, what commands validate it works. The draft doesn't need to be
  perfect — the builder refines it with real implementation knowledge.

Update `todos/{slug}/state.yaml`:

- Set `grounding.referenced_paths` to the list of file paths from the plan.
- Update `grounding.base_sha` to current HEAD.

If the todo is split instead, write:

- child todo artifacts
- updated holder `breakdown.todos`
- any dependency links needed in `todos/roadmap.yaml`

### 6. Enforce boundaries

- Do not invent behavior not grounded in requirements or codebase patterns.
- Do not rewrite approved requirements unless the plan is blocked by a genuine
  contradiction in those requirements.
- Do not change roadmap status beyond the child dependency links needed for a split.
- If blocked by uncertainty, record the blocker and continue with what is known.

## Outputs

1. Atomic case:
   `todos/{slug}/implementation-plan.md`, `todos/{slug}/demo.md`, and updated
   `todos/{slug}/state.yaml`.
2. Split case:
   child todos, dependency links, and updated holder `breakdown`.

## Recovery

1. If requirements are ambiguous, note the ambiguity in `dor-report.md` and derive the
   most likely interpretation. Mark it `[inferred]` in the plan.
2. If planning reveals the parent is not atomic, split it rather than stretching one
   builder plan past the session-size limit.
3. If a file referenced in requirements does not exist, verify whether it should be
   created or whether the requirement is stale.
