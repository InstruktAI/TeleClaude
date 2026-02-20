# Observability Blind Spot: Codex Sessions — Idea

**Status:** Technical debt observation
**Date:** 2026-02-20
**Source:** Memory review job analysis

## Observation

A recorded gotcha (2026-02-11):

> "Codex sessions unobservable until first turn completes"

This creates a visibility gap: when a Codex session is spawned, there is no way to know if it's working, stuck, or failed until it produces its first output. This is asymmetric with Claude and Gemini sessions which are observable immediately.

## Impact

- Debugging is harder (can't tail output early)
- Orchestrators can't detect startup failures
- Session lifecycle clarity is reduced
- Affects TTM (time to meaningful output)

## Related Issue

The ideas/ directory shows a series of related observability gaps:

- Session lifecycle spec (260220-session-lifecycle-spec.md)
- Session output linkability (260220-session-output-linkability.md)
- Session stop event hook design (260220-session-stop-event-hook-design.md)

These are all about the same root problem: **session observability is incomplete**.

## Consolidated Recommendation

Create a **Session Observability Carve-Out** spec that:

1. Defines what "observable" means for each session type (Claude, Gemini, Codex)
2. Requires hooks/events at startup, first output, status change, and termination
3. Ensures parity between session types
4. Provides orchestrators with a unified observability interface

## Next Step

Review existing session lifecycle specs in ideas/ and consolidate into a single, clear observability contract.
