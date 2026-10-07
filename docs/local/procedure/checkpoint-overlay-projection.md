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
- The quality-configuration assessment procedure (`/projects-assess-config`) is available and is started explicitly with `telec sessions run --command /projects-assess-config --path <project-root>`.
- The platform-universal base and the `ProjectConfig.checkpoint` overlay surface
  exist (`local/projects/teleclaude/design/architecture/checkpoint-system`,
  `local/projects/teleclaude/spec/domain/config`).

## Steps

1. The assessment session reads the codebase and infers the project's
   checkpoint maintenance: the source roots that constitute the `code` scope
   (onto which the base `test` / `log-check` actions attach), and the
   project's own runtime actions (build, restart, reload) named by make-contract
   convention (`make install` / `make test` / `make lint` work by convention).
2. Before declaring any inferred action, or an action id an existing binding
   already names, check it against the platform's base registries
   (`local/projects/teleclaude/design/architecture/checkpoint-system`'s base checkpoint and
   maintenance ids; `general/principle/grounding`). An id that already
   resolves there is reused as-is. For each action still needing a
   project-level declaration, the assessor decides which registry declares it,
   by one test:
   can the mechanism that performs the action establish its own outcome? A deterministic
   command — installing, restarting, reconciling dependencies, reloading — can, and is
   written into the maintenance registry as `command`, `main_only` and `precedence`, with no
   `run` and no `evidence`. An action whose substance is a judgment an
   agent makes and acts on cannot, and is written into the checkpoint registry as `run`, the
   `evidence` substrings that prove it ran (defaulting to `run`), `main_only`,
   `precedence`, and `evidence_must_follow_last_mutation` where ordering matters. An action
   id belongs to exactly one of the two registries; declaring the same id in both is
   rejected when the declaration is validated. The assessor then binds path scopes to action
   ids, referencing base action ids where they apply and declaring project actions
   otherwise; a binding names an id without regard to which registry declares it.
   <!-- planned:telec-sync-runs-maintenance -->

   Every maintenance action also carries its on-demand disposition
   (`local/projects/teleclaude/design/architecture/checkpoint-system`, Invariant 29).
   An action that disrupts a live process — restarting a service, reloading an
   interface — is written with `on_demand: defer`, plus an `owed_probe` when
   the project can tell whether that disruption is owed. Every other action
   keeps the default.
   <!-- /planned:telec-sync-runs-maintenance -->

3. The assessor writes the result into `ProjectConfig.checkpoint` via
   `telec config project patch --revision <rev> [--yaml <patch> | --from-file
<path>]` — never a direct edit of `teleclaude.yml`. The file's mutation is
   owned exclusively by the sealed config writer (`local/projects/teleclaude/spec/domain/config`:
   read-lock, validate the complete candidate, atomic replace); a direct edit
   bypasses both and only appears to converge when a later
   `telec config project init` happens to re-canonicalize the file. The merged
   base ⊕ overlay then drives the runtime structurally; the language flavoring
   lives only in this authoring step.
4. **Projection.** When the platform publishes a new project-declarable
   checkpoint paradigm — a new base action id, a new conventional kind, or a new
   declarable field — a new assessment session re-maps the paradigm
   onto each project's overlay. Re-assessment is idempotent: it converges the
   overlay to current truth and surfaces any conflict with a hand-authored
   deviation for human resolution rather than silently overwriting it.

### Step 5 — Capability projection

Assessment also writes the project's three capability toggles
(`local/projects/teleclaude/spec/feature/config/project-capability-manifest`) inferred from repo
shape: a make contract or language trees → `code`; snippet frontmatter under
`docs/` → `docs`; authored artifacts under `agents/` → `agents`, never `.agents/`. The initial
toggles are written by `telec config project init` before any
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

A greenfield project — no pre-existing git hooks — has nothing to assess here:
convergence installs the TeleClaude-owned set cleanly. A brownfield project's
existing hooks are assessed one at a time, by one test: does this hook's logic
already have a checkpoint or maintenance equivalent? If yes, translate it into
a binding (Steps 1–3) and remove the project hook so plumbing installs
TeleClaude's in its slot; this is the default outcome. If the logic has no
equivalent at all, leave the hook in place unmodified — plumbing never
overwrites a hook it did not write
(`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`). Only
when neither holds — logic with no equivalent that must still coexist with
TeleClaude's own dispatch — hand-author the hook without the sentinel, having
it itself call `telec code <hook-name>` alongside the project's own steps, and
name it explicitly in the assessment's output.

Verify convergence's result rather than its log lines alone: a project's own
pre-existing convention can redirect a platform-installed target that must
stay untracked machine state — canonically, a git hook via `core.hooksPath`
pointed at a tracked, in-repo directory — into committed content. Before
treating hook convergence as correct, confirm the installed hooks resolve
outside the tracked tree: `git config --get core.hooksPath` is unset or points
somewhere already untracked, and `git status` shows nothing new for the
installed hooks. A pre-existing override that redirects TeleClaude's own
plumbing into a tracked location is itself the slot conflict to reconcile:
unset it, strip any install script's guidance that sets it, and remove any
tracked payload it already caused to be committed.

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

- docs/local/design/architecture/checkpoint-system.md
- docs/local/spec/domain/config.md
