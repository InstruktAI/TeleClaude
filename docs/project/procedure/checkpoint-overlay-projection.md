---
description: How telec projects analyze infers and authors a project's checkpoint maintenance overlay, and the projection discipline that re-maps a newly published platform paradigm onto every project.
visibility: internal
activation_trigger: When extending the analyzer to author a project's checkpoint overlay, or when the platform publishes a new project-declarable checkpoint paradigm that existing projects must pick up.
delivered_by:
  - project-agnostic-checkpoint-payload
---

# Checkpoint Overlay Projection — Procedure

## Goal

Keep each onboarded project's checkpoint overlay convergent with what its
codebase actually owes. The analyzer authors the overlay from the codebase at
analyze-time; the runtime consumes the structured declaration forever with no
language or content detection. When the platform publishes a new
project-declarable paradigm, a re-analyze re-maps it onto every project.

## Preconditions

- The project is onboarded and carries a `teleclaude.yml` (`ProjectConfig`).
- `telec projects analyze` (`/projects-analyze`) is available.
- The platform-universal base and the `ProjectConfig.checkpoint` overlay surface
  exist (`project/design/architecture/checkpoint-system`,
  `project/spec/teleclaude-config`).

## Steps

1. `telec projects analyze` reads the codebase and infers the project's
   checkpoint maintenance: the source roots that constitute the `code` scope
   (onto which the base `lint` / `test` / `log-check` actions attach), and the
   project's own runtime actions (build, restart, reload) named by make-contract
   convention (`make install` / `make test` / `make lint` work by convention).
2. For each inferred action the analyzer writes a registry entry — `run`, the
   `evidence` substrings that prove it ran (defaulting to the command),
   `main_only`, `precedence`, and `evidence_must_follow_last_mutation` where
   ordering matters — and binds path scopes to action ids, referencing base
   action ids where they apply and declaring project actions otherwise.
3. The analyzer writes the result into `ProjectConfig.checkpoint` in the
   project's `teleclaude.yml`. The merged base ⊕ overlay then drives the runtime
   structurally; the language flavoring lives only in this authoring step.
4. **Projection.** When the platform publishes a new project-declarable
   checkpoint paradigm — a new base action id, a new conventional kind, or a new
   declarable field — a re-run of `telec projects analyze` re-maps the paradigm
   onto each project's overlay. Re-analysis is idempotent: it converges the
   overlay to current truth and surfaces any conflict with a hand-authored
   deviation for human resolution rather than silently overwriting it.

## Outputs

- A `ProjectConfig.checkpoint` overlay authored into the project's
  `teleclaude.yml`, consumed by the checkpoint engine.
- A re-projected overlay after a platform paradigm change.

## Recovery

- Unreadable or partial overlay → the runtime fails open to the base-only action
  set; a re-analyze regenerates the overlay.
- Analyzer uncertainty about a source root or runtime command → the analyzer
  records the gap for human confirmation rather than guessing a runtime
  detection path.

## See Also

- docs/project/design/architecture/checkpoint-system.md
- docs/project/spec/teleclaude-config.md
