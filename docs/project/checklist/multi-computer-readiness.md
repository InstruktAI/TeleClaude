---
id: project/checklist/multi-computer-readiness
type: checklist
scope: global
description: Verification steps before enabling multi-computer orchestration.
---

# Multi Computer Readiness — Checklist

## Required reads

- @docs/project/procedure/ssh-agent-keychain.md

## Purpose

Verify that all computers are correctly configured before enabling multi-computer orchestration.

## Preconditions

- TeleClaude is installed on each computer.

## Checks

- [ ] Unique computer names set in `config.yml`.
- [ ] Each computer uses a unique bot token.
- [ ] All bots are admins in the same Telegram supergroup.
- [ ] Redis reachable on all computers if using AI-to-AI collaboration.
- [ ] Exactly one computer has `telegram.is_master: true`.
- [ ] SSH agent/keychain configured and keys unlocked on remotes.
- [ ] Project paths added to `trusted_dirs` for MCP visibility.

## Recovery

- If a check fails, fix configuration and re-run the checklist before enabling orchestration.
