---
description: Kimi Code permission modes and documented rule configuration for the installed 0.37.2 CLI.
---

# Kimi Code Permissions

## Session modes

The installed CLI exposes three permission postures:

- `manual` is the documented default and prompts for approvals.
- `--yolo` auto-approves regular tool calls, while the agent may still ask
  questions.
- `--auto` makes the session autonomous: the agent handles approvals and does
  not ask questions.

`--yolo` and `--auto` are mutually exclusive. The vendor documents that print
mode (`kimi -p`) uses auto permission by default and cannot be combined with
`--yolo`, `--auto`, or `--plan`.

## Rules

The documented `[permission]` configuration has ordered
`[[permission.rules]]`: the first matching rule applies. A rule's `decision`
is `allow`, `deny`, or `ask`; its scope defaults to `user` when omitted.

The installed help has no sandbox flag or filesystem allowlist flag. This
runtime's documented permission system is approval/rule based; no separate
filesystem sandbox boundary was verified here.

## Gaps

- Permission-rule matching was not exercised against the installed runtime.
- No claim is made about the security strength of `yolo` or `auto`; they are
  approval-mode controls, not a verified containment boundary.

## Sources

- https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html
- https://moonshotai.github.io/kimi-code/en/configuration/config-files
