# DOR Report: default-agent-resolution

## Draft Assessment

### 1. Intent & success
**Pass.** Problem statement is explicit with a concrete call site inventory (input.md). Success criteria are testable grep commands and behavioral checks. The "what" and "why" are clear: eliminate DRY violation, enforce fail-fast, fix launcher visibility.

### 2. Scope & size
**Pass.** Work is atomic: one resolver function, config field, call site replacements, launcher fix. Fits a single session. Cross-cutting changes are justified (touching 8 files is inherent to centralizing a scattered pattern). No need for phase splitting.

### 3. Verification
**Pass.** Verification path is concrete: grep for zero hardcoded patterns, config parse-time validation tests, make test, make lint. Demo.md has executable validation commands. Edge cases identified: missing config key, disabled agent as default, unknown agent name.

### 4. Approach known
**Pass.** Technical path is straightforward: add config field, create resolver wrapping existing `assert_agent_enabled()`, replace call sites. All patterns already exist in the codebase (`assert_agent_enabled`, `get_enabled_agents`). No architectural decisions remain.

### 5. Research complete
**Pass (auto-satisfied).** No third-party dependencies. Discord `thread.edit(pinned=True)` is standard discord.py API — confirmed in input.md.

### 6. Dependencies & preconditions
**Pass.** No prerequisite tasks. Config change is backward-incompatible by design (intentional — clear error message guides user). No new config wizard exposure needed beyond the field itself.

### 7. Integration safety
**Pass.** Change can merge as a single commit. Rollback is straightforward (revert commit, remove config field). Entry points are explicit (config parse, resolver function). No risk of partial state.

### 8. Tooling impact
**Pass (auto-satisfied).** No scaffolding or tooling changes.

## Open Questions

1. **Transcript parser fallbacks**: `api_server.py:1109` and `api/streaming.py:125` use `AgentName.CLAUDE` as parser-selection fallbacks. These are NOT default agent resolution, but the "no hardcoded names" requirement is broad. Implementation plan defers these. Gate should confirm this scoping decision.
2. **Receiver hook fail-fast vs. fallback**: `hooks/receiver.py:190` catches ValueError and falls back to CLAUDE. The plan offers two approaches (use resolver or let it propagate). Gate should decide which aligns better with fail-fast policy in this context (checkpoint creation for unknown agent).

## Draft Verdict

Artifacts are strong. Call site inventory was incomplete (3 sites missed in original plan, now added). Demo fleshed out. Ready for formal gate validation.
