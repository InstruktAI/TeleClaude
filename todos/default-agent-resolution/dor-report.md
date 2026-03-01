# DOR Report: default-agent-resolution

## Gate Verdict: PASS (score 8)

### 1. Intent & success — PASS
Problem statement is explicit with a concrete call site inventory (input.md). Success criteria are testable grep commands and behavioral checks. The "what" and "why" are clear: eliminate DRY violation, enforce fail-fast, fix launcher visibility.

**Gate action**: Tightened success criterion for hardcoded strings to scope to "default-resolution paths" and added explicit deferral for `callback_handlers.py` user-selection buttons.

### 2. Scope & size — PASS
Work is atomic: one resolver function, config field, call site replacements, launcher fix. Fits a single session. Cross-cutting changes (8 files) are inherent to centralizing a scattered pattern. Phases are independently committable.

### 3. Verification — PASS
Verification path is concrete: grep for zero hardcoded patterns, config parse-time validation tests, `make test`, `make lint`. Edge cases identified: missing config key, disabled agent as default, unknown agent name.

### 4. Approach known — PASS
Technical path is straightforward: `assert_agent_enabled()` already exists in `core/agents.py`, resolver wraps it. All patterns exist in the codebase.

**Gate action**: Resolved the open decision on `receiver.py:190` — use config resolver (not propagate ValueError) because checkpoint data should not be lost for unknown agents.

### 5. Research complete — PASS (auto-satisfied)
No third-party dependencies. Discord `thread.edit(pinned=True)` is standard discord.py API.

### 6. Dependencies & preconditions — PASS
No prerequisite tasks. Config change is backward-incompatible by design (intentional — clear error message). No new config wizard exposure needed beyond the field.

### 7. Integration safety — PASS
Change can merge as a single commit or phased commits. Rollback: revert commit, remove config field. No partial state risk.

### 8. Tooling impact — PASS (auto-satisfied)
No scaffolding or tooling changes.

## Plan-to-Requirement Fidelity

All implementation plan tasks trace to requirements. No contradictions found.

Key alignment checks:
- Config field + parse-time validation → requirement "daemon refuses to start without it"
- Single `get_default_agent()` → requirement "only function that resolves"
- Call site inventory (14 sites) → verified against codebase grep; line numbers align
- Launcher thread pinning → requirement "sticky at top of forum"
- Launcher loop expansion → requirement "posted to ALL managed forums"
- Transcript parser fallbacks → explicitly deferred with justification (scoping note in plan)
- Callback handler buttons → explicitly deferred with justification (new Deferrals section in requirements)

## Codebase Verification

Spot-checked all call sites against live codebase:
- `"agent claude"` grep: 7 production sites (5 in plan + 1 deferred callback_handlers + 1 in tests)
- `enabled_agents[0]` grep: 4 production sites (all in plan)
- `AgentName.CLAUDE` grep: separated production defaults (4 in plan) from test fixtures and transcript parsers (correctly excluded)
- `_default_agent` / `_default_agent_name`: deletion targets confirmed at expected locations
- Launcher code: `_post_or_update_launcher`, `_pin_launcher_message`, forum loop at line 1793 — all verified

## Actions Taken

1. Scoped requirements success criterion for hardcoded strings to default-resolution paths
2. Added Deferrals section to requirements.md documenting callback_handlers.py exclusion
3. Resolved receiver hook decision in implementation plan Task 2.8 (use resolver)
4. Removed ambiguous "Or:" alternative from Task 2.8

## Resolved Open Questions

1. **Transcript parser fallbacks**: Confirmed correctly deferred. These select parser format, not launch agent. Making them fail-fast would break transcript display. Not default resolution.
2. **Receiver hook approach**: Resolved — use `get_default_agent()`. Checkpoint data preservation takes priority over strict fail-fast in this context.
