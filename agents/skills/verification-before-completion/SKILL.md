---
name: verification-before-completion
description: Evidence-before-claims gate. Use when about to claim work is complete, before committing or reporting done.
---

# Verification Before Completion

## Purpose

Prevent false completion claims by requiring fresh, explicit evidence before stating work is done, fixed, passing, or ready.

## Scope

Apply before any success claim, status handoff, commit, PR-ready statement, or "done" report.

Rule: run it, read it, confirm it.

## Inputs

- Claim to be made (for example: tests pass, bug fixed, lint clean).
- Verification command(s) that directly prove that claim.
- Current workspace state and latest outputs.

## Outputs

- Claim supported by fresh command evidence and exit status.
- If verification fails, an accurate status report with failure details.
- Explicit list of what was and was not verified.

## Procedure

1. Identify the exact claim.
2. Identify the exact command(s) that prove the claim.
3. Run full verification commands now (no stale or partial evidence).
4. Read complete output and exit codes.
5. Confirm output actually proves the claim.
6. Only then communicate success; otherwise report the real failing status.

Common failure patterns:

| Claim made       | Required evidence                                      | Invalid substitute                |
| ---------------- | ------------------------------------------------------ | --------------------------------- |
| "Tests pass"     | Fresh test run with zero failures                      | Prior run or assumption           |
| "Lint is clean"  | Fresh lint run with zero errors                        | Typecheck-only or partial lint    |
| "Bug is fixed"   | Reproduced failure no longer occurs + regression check | Code changed without reproduction |
| "Ready to merge" | Required gates completed and outputs reviewed          | "Looks correct" confidence        |

Red flags:

- "should", "probably", or "looks good" language without evidence.
- Declaring success before commands finish.
- Trusting another agent's claim without independent verification.
