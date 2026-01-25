---
id: guide/multi-computer-setup
type: guide
scope: global
description: Step-by-step guide for setting up a distributed TeleClaude network.
---

# Multi Computer Setup — Guide

## Goal

- @docs/project/checklist/multi-computer-readiness.md

- Set up a distributed TeleClaude deployment across multiple computers.

## Preconditions

- Telegram supergroup and bot tokens are available.
- Redis is available if AI-to-AI collaboration is required.

## Steps

1. Create a unique Telegram bot per computer and add all bots as admins to a Topics-enabled supergroup.
2. Install on each machine with `make install && make init`.
3. Configure `computer_name`, `telegram.is_master` (exactly one master), `redis_url`, and `trusted_dirs`.
4. Configure SSH keychain using the ssh-agent-keychain procedure.
5. Verify `make status` on all nodes.
6. Use `teleclaude__list_computers()` to confirm network discovery.

## Outputs

- Multi-computer network is online and visible to AI sessions.

## Recovery

- If discovery fails, re-check bot tokens, Redis connectivity, and `trusted_dirs`.
