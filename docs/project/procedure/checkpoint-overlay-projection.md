---
description: The projection discipline for a project's checkpoint maintenance overlay
  — how it is inferred, authored, and kept aligned with platform paradigms.
visibility: internal
---

# Checkpoint Overlay Projection — Procedure

## Goal

Keep each onboarded project's checkpoint overlay convergent with what its
codebase actually owes. Config assessment authors the overlay from the codebase
at assess-time — the overlay is config, so it lands in `teleclaude.yml` alongside
the rest of the project's tool configuration; the runtime consumes the structured
declaration forever with no language or content detection. When the platform
publishes a new project-declarable paradigm, a re-assess re-maps it onto every
project.

## Preconditions

- The project is onboarded and carries a `teleclaude.yml` (`ProjectConfig`).
- `telec projects assess` (`/projects-assess-config`) is available.
- The platform-universal base and the `ProjectConfig.checkpoint` overlay surface
  exist (`project/design/architecture/checkpoint-system`,
  `project/spec/domain/config`).

## Steps

1. `telec projects assess` reads the codebase and infers the project's
   checkpoint maintenance: the source roots that constitute the `code` scope
   (onto which the base `test` / `log-check` actions attach), and the
   project's own runtime actions (build, restart, reload) named by make-contract
   convention (`make install` / `make test` / `make lint` work by convention).
2. For each inferred action the assessor decides which registry declares it, by one test:
   can the mechanism that performs the action establish its own outcome? A deterministic
   command — installing, restarting, reconciling dependencies, reloading — can, and is
   written into the maintenance registry as `command`, `main_only` and `precedence`, with no
   `run` and no `evidence`, because nothing asks an agent to do it and nothing reads a
   transcript to find out whether it happened. An action whose substance is a judgment an
   agent makes and acts on cannot, and is written into the checkpoint registry as `run`, the
   `evidence` substrings that prove it ran (defaulting to `run`), `main_only`,
   `precedence`, and `evidence_must_follow_last_mutation` where ordering matters. An action
   id belongs to exactly one of the two registries; declaring the same id in both is
   rejected when the declaration is validated. The assessor then binds path scopes to action
   ids, referencing base action ids where they apply and declaring project actions
   otherwise; a binding names an id without regard to which registry declares it.
3. The assessor writes the result into `ProjectConfig.checkpoint` in the
   project's `teleclaude.yml`. The merged base ⊕ overlay then drives the runtime
   structurally; the language flavoring lives only in this authoring step.
4. **Projection.** When the platform publishes a new project-declarable
   checkpoint paradigm — a new base action id, a new conventional kind, or a new
   declarable field — a re-run of `telec projects assess` re-maps the paradigm
   onto each project's overlay. Re-assessment is idempotent: it converges the
   overlay to current truth and surfaces any conflict with a hand-authored
   deviation for human resolution rather than silently overwriting it.


### Step 5 — Capability projection

Assessment also writes the project's three capability toggles
(`project/spec/feature/config/project-capability-manifest`) inferred from repo
shape: a make contract or language trees → `code`; snippet frontmatter under
`docs/` → `docs`; authored artifacts under `agents/` → `agents`, never `.agents/`. The initial
toggles are written at onboard by `telec projects init` before any
capability-gated plumbing runs; this step refines them. Task tracking carries no
toggle — the manifest's existence is that subscription.


Assessment writes the toggles, and that write is the whole of the change: the
installed plumbing (git hooks, git wrapper) reads the toggles from the
declaration itself, so a new value takes effect on the next invocation with no
projection pass to run and nothing that can drift from it. Project-plumbing
convergence also reconciles the docs filter driver (present iff `docs`) and
refreshes the TeleClaude-owned git hooks of a project subscribing `code`, so an
already-onboarded repository's hooks converge on the declaration-reading source
on the next sync with no separate pass; a hook the project authored itself is
left in place. The `.gitattributes` docs line stays a one-time additive install
at onboard — disabling a capability edits no project-tracked file other than
the declaration carrying the toggle.


## Outputs

- A `ProjectConfig.checkpoint` overlay authored into the project's
  `teleclaude.yml`, consumed by the checkpoint engine.
- A re-projected overlay after a platform paradigm change.

## Recovery

- Unreadable or partial overlay → the runtime fails open to the base-only action
  set; a re-assess regenerates the overlay.
- Assessor uncertainty about a source root or runtime command → the assessor
  records the gap for human confirmation rather than guessing a runtime
  detection path.

## See Also

- docs/project/design/architecture/checkpoint-system.md
- docs/project/spec/domain/config.md
