# Requirements: ucap-ingress-provisioning-harmonization

## Problem

`unified-client-adapter-pipeline` split this phase to eliminate drift in two areas:

1. Input ingress semantics (how user input becomes internal commands with provenance).
2. Channel/provisioning orchestration (which adapters are provisioned and when).

Current code has strong building blocks (`CommandMapper`, `process_message`, `AdapterClient.ensure_ui_channels`)
but this phase must make the contract explicit and consistent across Web/TUI/Telegram/Discord.

## Goal

Define and enforce one ingress/provisioning behavior contract so adapter differences stay at the edge
and core behavior remains deterministic.

## Dependency

- Must execute after `ucap-canonical-contract` (`todos/roadmap.yaml` dependency).

## In Scope

- Harmonize command ingress mapping for interactive adapters (Web/TUI/Telegram/Discord) through shared command models.
- Standardize provenance updates (`origin`, actor attribution, `last_input_origin`) at common boundaries.
- Confirm and tighten `AdapterClient.ensure_ui_channels()` as the single UI channel provisioning funnel.
- Reduce duplicated per-adapter provisioning/routing decisions when the shared orchestration path already covers them.
- Add/adjust tests proving ingress/provisioning parity behavior.

## Out of Scope

- New UI features or presentation changes in Web/TUI/Telegram/Discord.
- Inbound webhook platform expansion and third-party normalizer research.
- Full migration/cutover orchestration and rollout metrics (handled by `ucap-cutover-parity-validation`).
- Architectural changes already scoped to other UCAP phases (`ucap-web-adapter-alignment`, `ucap-tui-adapter-alignment`).

## Functional Requirements

### R1. Unified ingress command mapping

- Interactive inputs from Web/TUI/Telegram/Discord must map into shared internal command models via
  `teleclaude/core/command_mapper.py` pathways.
- Mapping must preserve origin and actor attribution fields needed by downstream reflection/routing.

### R2. Provenance consistency

- `last_input_origin` must be updated consistently before user-facing fanout/feedback paths that depend on it.
- Provenance/actor metadata used for reflected input must not diverge by adapter.

### R3. Single provisioning orchestration boundary

- UI channel provisioning must remain orchestrated through `AdapterClient.ensure_ui_channels()` and adapter `ensure_channel()` implementations.
- Provisioning must stay adapter-aware (for example, Telegram customer-session skip) while following one core funnel.

### R4. Routing-policy alignment

- Ingress/provisioning behavior must align with:
  - `docs/project/spec/session-output-routing.md`
  - `docs/project/policy/adapter-boundaries.md`
- Core must avoid adapter-specific branching where shared routing/provisioning policies already define behavior.

### R5. Observability and failure clarity

- Error logs must identify adapter lane and session for ingress/provisioning failures.
- Behavior regressions should be detectable through targeted unit/integration checks.

## Non-Functional Requirements

- No third-party dependency additions in this phase.
- No destabilizing changes to daemon lifecycle/service management.
- Keep changes incremental and merge-safe behind existing boundaries.

## Success Criteria

1. Interactive input paths (Web/TUI/Telegram/Discord) produce consistent command/provenance semantics.
2. UI channel provisioning remains centralized and deterministic, with adapter-specific exceptions explicitly documented.
3. No contradictory ingress/provisioning behavior exists between requirements and implementation plan tasks.
4. Tests covering command mapping, provenance updates, and provisioning orchestration pass.

## Constraints

- Must preserve adapter/core boundary rules.
- Must not introduce direct host-level service operations.
- Must respect roadmap dependency ordering (`after: ucap-canonical-contract`).

## Risks

- Hidden adapter-specific edge cases may surface when removing duplicated logic.
- Incomplete boundary definition (interactive ingress vs hook ingress) can cause scope drift.
- Over-tight coupling between provenance and delivery behavior could introduce subtle regressions without focused tests.
