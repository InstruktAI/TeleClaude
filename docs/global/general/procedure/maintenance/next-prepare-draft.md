---
id: 'general/procedure/maintenance/next-prepare-draft'
type: 'procedure'
scope: 'global'
description: 'Plan drafting phase for next-prepare. Derives implementation-plan.md from approved requirements. Single-agent work.'
---

# Next Prepare Plan Draft — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md

## Goal

Produce `implementation-plan.md` from approved `requirements.md`. This is a single-agent
phase — requirements derivation is handled by the triangulation team, not here.

The plan must be detailed enough for a builder to execute without guessing, and
review-aware enough that the reviewer finds no surprises.

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

### 2. Draft the implementation plan

Structure the plan as an ordered task list. Each task must include:

- **What**: the concrete change (file, function, component).
- **Why**: the rationale for the approach. This prevents the builder from taking shortcuts.
  If the plan says "use adapter pattern" but doesn't say why, the builder may inline the
  logic instead. The "why" is the guard against drift.
- **Verification**: how the builder confirms the task is done (test to write, behavior to
  observe, lint to pass).
- **Referenced files**: exact file paths that will be created or modified. These are
  extracted into `state.yaml.grounding.referenced_paths` for staleness detection.

### 3. Anticipate review lanes

The plan must pre-satisfy what the reviewer will check. For each requirement:

- If it implies new behavior: plan includes corresponding test tasks.
- If it touches CLI: plan includes help text update task.
- If it introduces config surface: plan includes config wizard, sample, and spec update tasks.
- If it touches security boundaries: plan includes input validation and auth check tasks.
- If it introduces new code paths: plan states which patterns to follow and why.

A plan that does not anticipate review lanes will produce review findings that cost
more to fix than they cost to prevent.

### 4. Write artifacts

Write:

- `todos/{slug}/implementation-plan.md` — the full plan with tasks, rationale, and verification.
- `todos/{slug}/demo.md` — draft demonstration plan: what medium (CLI, TUI, web, API),
  what the user observes, what commands validate it works. The draft doesn't need to be
  perfect — the builder refines it with real implementation knowledge.

Update `todos/{slug}/state.yaml`:

- Set `grounding.referenced_paths` to the list of file paths from the plan.
- Update `grounding.base_sha` to current HEAD.

### 5. Enforce boundaries

- Do not invent behavior not grounded in requirements or codebase patterns.
- Do not make architectural decisions — if the approach is genuinely unclear, write
  blockers to `dor-report.md` and stop.
- Do not change roadmap status.
- If blocked by uncertainty, record the blocker and continue with what is known.

## Outputs

1. `todos/{slug}/implementation-plan.md` — review-aware, rationale-rich.
2. `todos/{slug}/demo.md` — draft demonstration plan.
3. `todos/{slug}/state.yaml` — grounding metadata with referenced paths.

## Recovery

1. If requirements are ambiguous, note the ambiguity in `dor-report.md` and derive the
   most likely interpretation. Mark it `[inferred]` in the plan.
2. If a file referenced in requirements does not exist, verify whether it should be
   created or whether the requirement is stale.
