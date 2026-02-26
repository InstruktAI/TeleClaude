# Requirements: config-wizard-redesign

## Goal

Redesign the Textual config wizard into a guided, editable setup flow so an operator can complete standard adapter configuration without leaving the TUI.

## Context

- `teleclaude/cli/tui/views/config.py` is the active Textual config surface but currently renders flat, read-only Rich text.
- `teleclaude/cli/tui/views/configuration.py` remains as a legacy curses fallback.
- `config-wizard-whatsapp-wiring` is a roadmap dependency and should land before this redesign so WhatsApp appears in the same UX model.

## Scope

### In scope

1. Redesign `teleclaude/cli/tui/views/config.py` to present clear visual hierarchy (section/card style groups instead of a flat list).
2. Add per-adapter status classification in the Textual view: `configured`, `partial`, `unconfigured`, plus an overall progress summary.
3. Add inline env var editing in the Textual config view with explicit save/cancel behavior.
4. Persist env updates via shared config-layer helpers (no ad-hoc direct env file writes inside view rendering code).
5. Implement guided onboarding flow with ordered steps and visible progress through adapters and core tabs.
6. Replace the Notifications placeholder with a real actionable surface (read-only summary + next action is acceptable for this todo).
7. Preserve keyboard-first navigation and existing validate/refresh actions.

### Out of scope

- Full redesign/parity for legacy curses `configuration.py`.
- New adapter logic or env registry expansions (handled by other todos).
- Rework of person-management flows outside the config wizard.
- Automatic daemon restart behavior from the wizard.

## Success Criteria

- [ ] **SC-1**: Config tab shows grouped adapter sections with explicit `configured|partial|unconfigured` status labels derived from registered env vars.
- [ ] **SC-2**: Overall completion summary is visible at a glance (for example `3/5 sections configured`) and updates after edits.
- [ ] **SC-3**: Selecting an env var and pressing Enter opens inline edit mode; save writes the new value and cancel leaves current value unchanged.
- [ ] **SC-4**: Env edits persist to the resolved env file and update process environment for immediate in-session validation.
- [ ] **SC-5**: Guided mode advances through a deterministic sequence and shows current step/total progress.
- [ ] **SC-6**: Notifications tab no longer renders the literal `(Not implemented yet)` string.
- [ ] **SC-7**: Existing validation trigger (`v`) still runs config validation and renders an updated pass/fail summary.
- [ ] **SC-8**: Automated coverage exists for env persistence helper behavior and core config view interaction logic.

## Constraints

- Textual is the primary target; legacy curses remains fallback-only in this todo.
- Data writes must go through shared config helpers in `teleclaude/cli/config_handlers.py`.
- Preserve existing tab identifiers (`adapters`, `people`, `notifications`, `environment`, `validate`) to avoid state/persistence regressions.
- Do not print full secret values in status messages or logs after edit operations.

## Risks

- Scope can sprawl across UI, state, and persistence if notifications/editor behavior is not tightly bounded.
- Incorrect env file resolution can cause edits to be written to the wrong file in overridden environments.
- Inline editing can introduce accidental disclosure risk if edited values are echoed in clear text.
