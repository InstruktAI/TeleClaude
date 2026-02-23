# DOR Report: tui-footer-clickable-agents

## Gate Verdict: PASS (score 9/10)

All DOR criteria satisfied. The plan adds `degraded_until` to the data model to enable timed degradation without conflating it with unavailable state.

## Assessment

### Intent & Success

**Pass.** Clear 3-click cycle: available → degraded (1h, still manually selectable) → unavailable (1h, fully disabled) → available.

### Scope & Size

**Pass.** Touches db model, db methods, api_server, api_client, status_bar, app.py. Slightly larger than a 3-file change but still atomic and fits a single session.

### Verification

**Pass.** Testable via API endpoint tests, expiry logic tests, and manual TUI verification.

### Approach Known

**Pass.** All building blocks exist. The key addition is `degraded_until` column — a clean parallel to `unavailable_until` that preserves the semantic distinction between degraded and unavailable.

### Plan-to-Requirement Fidelity

**Pass.** Every plan task traces to a requirement. Degraded and unavailable are kept as genuinely distinct states in the db, matching the user's intent.

### Research

**N/A.** No third-party dependencies.

### Dependencies

**Pass.** No prerequisite todos.

### Integration Safety

**Pass.** Additive: new column, new endpoint, new click handler. SQLModel handles new nullable columns without migration issues.

### Tooling Impact

**N/A.**

## Codebase Verification

| Claim                                                              | Verified | Notes                                                                                            |
| ------------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------ |
| `AgentAvailability` model in `db_models.py`                        | Yes      | Lines 105-114. Has `agent`, `available`, `unavailable_until`, `reason`. No `degraded_until` yet. |
| `mark_agent_degraded` sets `unavailable_until=None`                | Yes      | `db.py:1199`. No expiry support for degraded state.                                              |
| `clear_expired_agent_availability` only checks `unavailable_until` | Yes      | `db.py:1217`. Needs extension for `degraded_until`.                                              |
| `AgentAvailabilityDTO` in `api_models.py`                          | Yes      | Lines 208-218. Has `unavailable_until` but no `degraded_until`.                                  |
| `StatusBar.on_click` handles right-side toggles                    | Yes      | `status_bar.py:168-179`. Agent pills on the left have no click regions.                          |

## Open Questions

None.

## Assumptions

- 1-hour fixed duration for both degraded and unavailable (per user input: "for I would say an hour").
- `SettingsChanged` message reused for agent status clicks.
- SQLModel auto-creates the new column on startup (no manual migration needed).
