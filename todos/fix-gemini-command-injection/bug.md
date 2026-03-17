# Bug: Enter key submission after agent command injection is brittle and fails regularly

## Symptom

Enter key submission after agent command injection is brittle and fails regularly

## Detail

## Symptom

When dispatching a Gemini worker via `telec sessions run`, the /next-bugs-fix command is injected into the Gemini CLI prompt but the enter key submission fails silently. Gemini launches, shows its prompt with the command text visible, but never processes it — the session sits idle at the input prompt indefinitely.

## Reproduction

1. `telec sessions run --command /next-bugs-fix --args fix-git-wrapper-reset --project /Users/Morriz/Workspace/InstruktAI/TeleClaude --agent gemini --mode med --subfolder trees/fix-git-wrapper-reset`
2. Tail the session — Gemini shows its startup banner and prompt but no assistant response
3. The command text appears in the terminal but was never submitted

## Evidence

Session b7ce4768-a64c-478c-a951-839cc728c1a1 (2026-03-17) — Gemini sat at prompt for 10+ minutes without processing the injected command.

## Impact

Gemini workers cannot be dispatched reliably as fallback when Claude hits rate limits. The orchestrator has no way to detect the failure except by polling and finding no output.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
