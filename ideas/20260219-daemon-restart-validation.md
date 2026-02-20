# Daemon Restart Validation Discipline — Friction Pattern

**ID:** 20260219-daemon-restart-validation
**Status:** Idea
**Severity:** High
**Frequency:** Recurring (reported 2026-02-09)

## The Problem

AIs consistently fail to run `make restart` after code changes, then claim validation passed against stale (pre-change) daemon state. This is a recurring pattern that undermines trust in agent-reported test results and verification.

The checkpoint procedure requires daemon restart before validation, but agents either:

1. Forget to restart
2. Restart in isolation without verification
3. Report "tests passed" against old code

### Evidence

- Memory #25 (FRICTION): "AIs consistently fail to run make restart after code changes, then claim validation passed against stale (pre-change) daemon state. This is a recurring pattern that undermines trust."
- Pattern observed across multiple agent sessions
- Similar to "always restart daemon after code changes" entry point in procedures

## Root Cause Analysis

- **No enforcement:** The rule exists in documentation but nothing prevents stale daemon execution
- **Invisible failure:** Tests pass silently against old code; no immediate feedback
- **Cognitive burden:** Requires manual recall of the restart step

## Solutions to Explore

1. **Procedural enforcement** (near-term)
   - Add explicit "restart and verify alive" checkpoint to worker procedures
   - Require restart before any test/validation invocation
   - Create a guard wrapper: `validate` tool that internally calls `make restart`

2. **Automation** (medium-term)
   - Make `make test` automatically restart the daemon first
   - Add daemon version check before validation (error if mismatch)
   - Watchdog: detect code changes and refuse test runs without restart

3. **Architecture fix** (long-term)
   - Simplify restart requirements by reducing coupling between code and running daemon
   - Allow side-by-side daemon versions during deployment

## Impact

- **Trust:** Validation results reliably reflect current code
- **Speed:** No wasted debugging cycles on stale daemon failures
- **Discipline:** Hardens the checkpoint-validate-commit cycle

## Related

- AGENTS.md: "TUI work" section requires SIGUSR2 reload instead of daemon restart
- Agent Job Hygiene procedure: "Fix forward — you own the outcome"
- Software Development Lifecycle: checkpoint procedures

## Next Step

Recommend automation approach: wrap test/validate invocations with automatic daemon restart verification.
