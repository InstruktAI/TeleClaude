---
description: Kimi Code 0.37.2 hook registration, installed event evidence, and permission-only response capability.
---

# Kimi Code Hooks

## Configuration

Kimi Code registers hook rules in `[[hooks]]` entries in `config.toml`. The
documented fields are `event`, optional regular-expression `matcher`,
`command`, and optional `timeout`; the vendor documents a 1–600 second timeout
range with a 30-second default. Hook commands receive JSON on standard input.

The installed 0.37.2 binary contains the `hooks` configuration surface and
these event names: `PreToolUse`, `PostToolUse`, `UserPromptSubmit`,
`SessionStart`, `SessionEnd`, `Stop`, `SubagentStop`, `Notification`, and
`PreCompact`.

## Background execution

Kimi Code 0.37.2 has no configured async/background hook facility. A
`[[hooks]]` entry accepts only `event`, `matcher`, `command`, and `timeout`;
extra fields make the configuration fail to load. It documents neither an
`asyncRewake` equivalent nor a completion-triggered turn.

Matching hooks may run in parallel, and non-blockable events are described as
fire-and-forget, but neither behavior is a marked asynchronous hook with a
deferred model-injection channel. In particular, the documented observation
events do not let return values affect the main flow. The vendor is silent on
any safe-point delivery of a background hook's output, so no such delivery or
per-event async allowance is established.

## Response boundary

The installed binary contains `hookSpecificOutput.permissionDecision` and
`hookSpecificOutput.permissionDecisionReason`. It contains zero occurrences of
`additionalContext`; therefore, for 0.37.2 the verified Claude-shaped output
envelope supports permission decisions but not hook-driven context injection.

The current vendor Hooks guide describes a broader and evolving hook surface.
It is a useful configuration reference, but it does not supersede the installed
binary when the two differ.

## Gaps

- No live hook run verified stdin payload fields, matcher behavior, timeout
  handling, or stdout/exit-code handling.
- The installed binary exposes additional hook-related strings, but this record
  only names the event set verified for the current runtime contract.

## Sources

- https://moonshotai.github.io/kimi-code/en/customization/hooks
