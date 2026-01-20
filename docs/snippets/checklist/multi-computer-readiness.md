---
id: checklist/multi-computer-readiness
type: checklist
scope: global
description: Verification steps before enabling multi-computer orchestration.
---

# Multi-Computer Readiness Checklist

- [ ] **Unique Computer Names**: Each computer has a distinct `computer_name` in `config.yml`.
- [ ] **Bot Tokens**: Each computer uses its own unique bot token (shared tokens cause polling collisions).
- [ ] **Supergroup Access**: All bots are members and admins of the same Telegram supergroup.
- [ ] **Redis Connection**: (If using AI-to-AI) All computers can reach the same Redis instance.
- [ ] **Master Designation**: Exactly ONE computer has `telegram.is_master: true`.
- [ ] **SSH Agent**: `keychain` is configured and keys are unlocked on all remote machines.
- [ ] **Trust**: Project directories are added to `trusted_dirs` for MCP visibility.