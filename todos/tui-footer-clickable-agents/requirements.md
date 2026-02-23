# Requirements: tui-footer-clickable-agents

## Goal

Make agent name pills in the TUI footer (StatusBar) clickable to cycle through availability states: available → degraded → unavailable → available. This gives the user direct manual control over agent dispatch status without leaving the TUI.

## Scope

### In scope

- Clicking an agent pill in the StatusBar cycles its status through: available → degraded (1h) → unavailable (1h) → available.
- The state change persists via the daemon API (same path as MCP `mark_agent_status`).
- The StatusBar refreshes immediately to reflect the new status.
- Duration for degraded and unavailable is 1 hour from the click moment.

### Out of scope

- Custom duration selection (modal/prompt for choosing how long).
- Keyboard shortcuts for agent status toggling.
- Right-click or long-press for additional options.
- Changes to the curses-based Footer class (legacy, being replaced).

## Success Criteria

- [ ] Clicking an available agent pill marks it degraded (with `~` indicator) for 1 hour.
- [ ] Clicking a degraded agent pill marks it unavailable (with `✘` indicator and countdown) for 1 hour.
- [ ] Clicking an unavailable agent pill marks it available (with `✔` indicator).
- [ ] Status change round-trips through the API server — not direct db access from the TUI.
- [ ] StatusBar visually updates immediately after click without waiting for the next periodic refresh.
- [ ] All three agents (claude, gemini, codex) support the click cycle independently.

## Constraints

- The TUI is a client of the API server; it must not import or call db methods directly.
- A new API endpoint is required since `POST /agents/{agent}/status` does not exist yet.
- Degraded and unavailable are semantically distinct states: degraded excludes from auto-dispatch but remains manually selectable; unavailable is fully disabled. The data model must preserve this distinction — `degraded_until` as a new column parallel to `unavailable_until`, not a hack via reason prefixes.
- Reuse and extend existing db methods (`mark_agent_available`, `mark_agent_degraded`, `mark_agent_unavailable`).
- The click handling must coexist with existing right-side toggle clicks without interference.

## Risks

- Accidental clicks could disable an agent unintentionally. Mitigated by the 3-state cycle: the worst case is one extra click to cycle back to available.
