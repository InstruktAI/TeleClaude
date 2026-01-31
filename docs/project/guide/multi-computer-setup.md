---
id: project/guide/multi-computer-setup
type: guide
scope: project
description: Guide for setting up a distributed TeleClaude network.
---

# Multi Computer Setup — Guide

## Required reads

- @docs/project/checklist/multi-computer-readiness.md

## Goal

Set up a distributed TeleClaude deployment across multiple computers.

## Context

TeleClaude can operate across multiple machines, each running its own daemon with a unique Telegram bot. Computers discover each other via Redis heartbeats and route commands through Redis Streams. Exactly one computer acts as the Telegram master (handles shared group interactions), while all computers can host AI sessions.

## Approach

1. Create a unique Telegram bot per computer and add all bots as admins to a Topics-enabled supergroup.
2. Install on each machine with `make install && make init`.
3. Configure `computer_name`, `telegram.is_master` (exactly one master), `redis_url`, and `trusted_dirs`.
4. Configure SSH keychain using the ssh-agent-keychain procedure.
5. Verify `make status` on all nodes.
6. Use `teleclaude__list_computers()` to confirm network discovery.

## Pitfalls

- Multiple computers with `telegram.is_master: true` — causes duplicate command handling and message collisions.
- Reusing bot tokens across computers — Telegram will deliver updates to only one instance.
- Missing `trusted_dirs` entries — MCP tools won't expose projects on that computer.
- Redis unreachable — cross-computer commands silently fail; local operations still work.
