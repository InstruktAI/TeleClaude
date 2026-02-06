---
id: 'project/procedure/multi-computer-setup'
type: 'procedure'
scope: 'project'
description: 'Guide for setting up a distributed TeleClaude network.'
---

# Multi Computer Setup — Procedure

## Goal

Set up a distributed TeleClaude deployment across multiple computers.

## Preconditions

- One Telegram bot token per computer.
- Redis reachable by all nodes.
- Access to each machine to install and configure TeleClaude.

## Steps

1. Create a unique Telegram bot per computer and add all bots as admins to a Topics-enabled supergroup.
2. Install on each machine with `make install && make init`.
3. Configure `computer_name`, `telegram.is_master` (exactly one master), `redis_url`, and `trusted_dirs`.
4. Configure SSH keychain using the ssh-agent-keychain procedure.
5. Verify `make status` on all nodes.
6. Use `teleclaude__list_computers()` to confirm network discovery.

## Outputs

- Multi-node TeleClaude deployment with Redis discovery working.
- One Telegram master configured and verified.

## Recovery

- Multiple computers with `telegram.is_master: true` — causes duplicate command handling and message collisions.
- Reusing bot tokens across computers — Telegram will deliver updates to only one instance.
- Missing `trusted_dirs` entries — MCP tools won't expose projects on that computer.
- Redis unreachable — cross-computer commands silently fail; local operations still work.
