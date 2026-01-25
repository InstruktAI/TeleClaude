---
id: checklist/multi-computer-readiness
type: checklist
scope: global
description: Verification steps before enabling multi-computer orchestration.
---

# Multi Computer Readiness — Checklist

## Goal

- @docs/procedure/ssh-agent-keychain

- Verify readiness for multi-computer orchestration.

- TeleClaude is installed on each computer.

- [ ] Unique computer names set in `config.yml`.
- [ ] Each computer uses a unique bot token.
- [ ] All bots are admins in the same Telegram supergroup.
- [ ] Redis reachable on all computers if using AI-to-AI collaboration.
- [ ] Exactly one computer has `telegram.is_master: true`.
- [ ] SSH agent/keychain configured and keys unlocked on remotes.
- [ ] Project paths added to `trusted_dirs` for MCP visibility.

- Multi-computer setup can operate without command collisions.

- If a check fails, fix configuration and re-run the checklist before enabling orchestration.

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
