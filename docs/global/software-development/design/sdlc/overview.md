---
id: 'software-development/design/sdlc/overview'
type: 'design'
domain: 'software-development'
scope: 'global'
description: 'Top-level software development lifecycle design: shared artifact authority, role lenses, rigor model, and phase boundaries.'
---

# SDLC Overview — Design

## Required reads

- @~/.teleclaude/docs/software-development/principle/externalized-structural-context.md

## Purpose

Define the top-level software development lifecycle used by the platform.

This design is intentionally above machine implementation details. It defines:

- the phase boundaries of the lifecycle
- the authority relationship between lifecycle artifacts
- the role lenses used to produce high-quality artifacts and changes
- the split between automation and judgment

The lifecycle is designed for autonomy without losing rigor.

## Inputs/Outputs

**Inputs**

- problem impulse, context, and existing artifacts
- current codebase and system reality
- computed supporting context where automation can provide it

**Outputs**

- aligned lifecycle artifacts
- implemented software change
- reviewed and integrated system change

## Invariants

- Downstream work derives from upstream artifact authority instead of
  re-inventing it.
- `requirements` and `test-specs` stay in the same hot scope so acceptance does
  not drift from intent.
- `implementation-plan` derives from both `requirements` and `test-specs`.
- Automation computes what can be computed so human and AI judgment can focus on
  interpretation, trade-offs, and decisions.
- Structural context is an SDLC input where available; it does not replace
  judgment.
- Humans enter at explicit judgment touchpoints rather than through accidental
  hidden process breaks.
- AI performs most artifact and code work, but only inside explicit artifact and
  process boundaries.

## Primary flows

### Prepare

Prepare turns a problem impulse into aligned build artifacts.

Produces:

- `requirements`
- `test-specs`
- `implementation-plan`

Rigor is preserved by:

- converging requirements before downstream work
- keeping specs close to requirements while context is hot
- deriving the plan from both requirements and specs
- using lead/support counter-pressure during artifact authoring

### Work

Work realizes the prepared artifacts in code.

Flow:

- build
- review
- fix
- review again
- repeat until approved

Rigor is preserved by:

- building against the authoritative artifact chain
- reviewing against intent, acceptance, execution, and quality
- re-validating every fix instead of assuming patches are safe

### Integration

Integration turns locally valid changes into globally safe system truth under
concurrent delivery.

Rigor is preserved by:

- considering queue context and overlap before landing
- making sequencing explicit instead of accidental
- validating cutover safety and post-landing system coherence

### Shared role lenses

The lifecycle uses two stable lenses:

- `A`: intent, scope, meaning, outcome fidelity
- `B`: rigor, precision, structure, execution realism

The lens is authoritative. The current default mapping is `A` = Claude,
`B` = Codex — but the lenses define the roles, not the vendors.

Lead/support by artifact or step:

| Lifecycle element     | Lead | Support |
| --------------------- | ---- | ------- |
| `requirements`        | `A`  | `B`     |
| `test-specs`          | `A`  | `B`     |
| `implementation-plan` | `B`  | `A`     |
| `build`               | `B`  | `A`     |
| `review`              | `A`  | `B`     |
| `fix`                 | `B`  | `A`     |

Integration does not follow the lead/support split. Both lenses are active
simultaneously: `A` guards whether landing preserves intended system behavior,
`B` guards whether the sequencing and cutover are mechanically safe. Neither
leads — the integration decision requires both perspectives at once.

### Shared rigor model

The lifecycle preserves rigor by combining:

- explicit artifact authority
- explicit review and approval boundaries
- lead/support counter-pressure from opposing lenses
- aggressive supporting automation that computes facts for judgment

### Persistent quality focus points

These are continuous pressures across the lifecycle, not isolated later phases:

- correctness
- security
- maintainability
- performance
- observability
- operability
- simplicity
- integration fit
- product fidelity

## Failure modes

- `test-specs` drift from `requirements` because they are written cold or too
  late.
- `implementation-plan` drifts from `requirements` and `test-specs` because it
  is treated as an independent reinterpretation.
- Builders consume only one artifact and lose the full authority chain.
- Review checks only local correctness and ignores intent or acceptance.
- Integration is treated as “merge after approval” instead of concurrency-safe
  system convergence.
- Structural context is unavailable or ignored, causing grep-driven planning,
  duplicated paths, zombie code, and hidden impact.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md —
  operational steps and state machine commands for executing this lifecycle
