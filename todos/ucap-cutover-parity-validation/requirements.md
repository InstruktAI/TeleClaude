# Requirements - ucap-cutover-parity-validation

## Problem

Even after lane migrations, production safety depends on parity validation, cutover controls, and rollback criteria to avoid regressions or duplicate delivery.

## Goal

Run a greenfield pilot cutover of the unified adapter pipeline with lightweight, explicit safety checks before bypass retirement.

## Dependencies

- Must run after `ucap-web-adapter-alignment`.
- Must run after `ucap-tui-adapter-alignment`.
- Must run after `ucap-ingress-provisioning-harmonization`.

## In Scope

- Shadow mode enablement and parity comparison logic.
- Explicit parity criteria and rollback triggers.
- Final retirement checks for legacy bypass paths.
- End-to-end validation across Web/TUI/Telegram/Discord.

## Out of Scope

- New product features unrelated to transport contract unification.
- Architecture changes to core contract shape.

## Functional Requirements

### R1. Controlled shadow/cutover

- Run shadow mode for three representative pilot sessions before full cutover.
- Cutover is blocked unless pilot parity checks pass.

### R2. Parity criteria and rollback triggers

- Use lightweight pilot criteria:
  - No missing outputs in any client for each pilot session.
  - At most one duplicate output event per pilot session.
- Rollback trigger: any missing output in any client, or more than one duplicate output event in a pilot session.
- Rollback exit: rerun the failed pilot scenario and require one clean pass (no missing outputs, at most one duplicate) before reattempting cutover.

### R3. Legacy bypass retirement validation

- Verify legacy bypass paths are not used for core output progression after cutover.

### R4. Cross-client validation

- Validate equivalent session visibility and output progression across Web/TUI/Telegram/Discord for three representative scenarios.

## Acceptance Criteria

1. Shadow mode runs for three representative pilot sessions and results are documented.
2. For each pilot session, outputs are visible in Web/TUI/Telegram/Discord with no missing outputs and at most one duplicate output event.
3. Rollback is exercised once and evidence shows return to known-good behavior before reattempting cutover.
4. No legacy bypass path is exercised in cutover validation.
5. Demo artifacts capture commands, observed outcomes, and residual risk notes.

## Greenfield Pilot Defaults

1. This todo is a pilot-safety gate, not final production hardening.
2. Strict percentage-based SLO thresholds are deferred to a follow-up hardening todo.

## Risks

- Hidden lane-specific assumptions can cause post-cutover regressions.
- Pilot-level thresholds may miss low-frequency production issues; follow-up hardening is required before broad rollout.
