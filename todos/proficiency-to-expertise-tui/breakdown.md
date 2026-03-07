# Breakdown: proficiency-to-expertise-tui

## Assessment

**Splitting not needed.** TUI changes are concentrated in two files (config.py,
guidance.py). The wizard step, display, and editing pattern are tightly coupled —
they must ship together for a coherent user experience.

## DOR Gate Assessment

| Gate | Status | Evidence |
|------|--------|----------|
| 1. Intent & success | Pass | TUI wizard displays and edits structured expertise fields |
| 2. Scope & size | Pass | 2 files (config.py + guidance.py), single UI domain |
| 3. Verification | Pass | Visual verification via TUI reload (SIGUSR2), guided wizard flow |
| 4. Approach known | Pass | Existing enum cycling pattern for role, extend to domain/sub-area fields |
| 5. Research complete | Auto-pass | No new third-party dependencies |
| 6. Dependencies | Pass | Depends on schema child (proficiency-to-expertise-schema) |
| 7. Integration safety | Pass | TUI changes are self-contained; no API or hook impact |
| 8. Tooling impact | Pass | Config wizard updated as part of scope |

**Score: 8 / 10** — Status: **pass**
