---
description: 'Top-level software development lifecycle design: shared artifact authority, role lenses, rigor model, and phase boundaries.'
visibility: 'public'
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
- PRD intent and feature-spec acceptance scenarios stay in the same hot scope
  so acceptance does not drift from intent.
- `implementation-plan` derives from PRD intent, optional architecture, and
  in-scope feature-spec scenarios.
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

Prepare turns a problem impulse into aligned build artifacts through a
persistent pair of workers.

Produces:

- `prd`
- optional `architecture`
- `implementation-plan`

Rigor is preserved by:

- pair-based discovery that surfaces hidden assumptions before writing
- converging PRD intent before downstream work
- human approval of the PRD before derived artifacts
- keeping acceptance scenarios close to intent while context is hot
- deriving the plan from PRD intent, optional architecture, and scenarios
- turn-based writer/reviewer accountability for each artifact

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
`B` = Codex — but the lenses define who the workers ARE, not the vendors.

During discovery, there are no roles — both lenses explore freely. Roles
(writer, reviewer) are assigned only when an artifact needs to be produced.

Writer/reviewer by artifact or step:

| Lifecycle element     | Writer | Reviewer | Mode       |
| --------------------- | ------ | -------- | ---------- |
| `discovery`           | —      | —        | pair-based |
| `prd`                 | `A`    | human    | turn-based |
| `architecture`        | `A`    | `B`      | turn-based |
| `implementation-plan` | `B`    | `A`      | turn-based |
| `build`               | `B`    | —        | turn-based |
| `review`              | —      | `A`      | turn-based |
| `fix`                 | `B`    | —        | turn-based |

Integration does not follow the writer/reviewer split. Both lenses are active
simultaneously: `A` guards whether landing preserves intended system behavior,
`B` guards whether the sequencing and cutover are mechanically safe. Neither
writes alone — the integration decision requires both perspectives at once.

### Shared rigor model

The lifecycle preserves rigor by combining:

- explicit artifact authority
- explicit review and approval boundaries
- pair-based discovery that surfaces what one perspective would miss
- turn-based production with review from the other lens
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

- Feature-spec acceptance scenarios drift from PRD intent because they are
  written cold or too late.
- `implementation-plan` drifts from PRD intent and feature-spec scenarios
  because it is treated as an independent reinterpretation.
- Builders consume only one artifact and lose the full authority chain.
- Review checks only local correctness and ignores intent or acceptance.
- Integration is treated as “merge after approval” instead of concurrency-safe
  system convergence.
- Structural context is unavailable or ignored, causing grep-driven planning,
  duplicated paths, zombie code, and hidden impact.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md —
  operational steps and state machine commands for executing this lifecycle
