---
id: checklist/multi-computer-readiness
type: checklist
scope: global
description: Verification steps before enabling multi-computer orchestration.
---

## Goal

- Verify readiness for multi-computer orchestration.

## Preconditions

- TeleClaude is installed on each computer.

## Steps

- [ ] Unique computer names set in `config.yml`.
- [ ] Each computer uses a unique bot token.
- [ ] All bots are admins in the same Telegram supergroup.
- [ ] Redis reachable on all computers if using AI-to-AI collaboration.
- [ ] Exactly one computer has `telegram.is_master: true`.
- [ ] SSH agent/keychain configured and keys unlocked on remotes.
- [ ] Project paths added to `trusted_dirs` for MCP visibility.

## Outputs

- Multi-computer setup can operate without command collisions.

## Recovery

- If a check fails, fix configuration and re-run the checklist before enabling orchestration.
