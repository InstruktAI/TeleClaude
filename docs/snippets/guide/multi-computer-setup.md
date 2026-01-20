---
id: guide/multi-computer-setup
type: guide
scope: global
description: Step-by-step guide for setting up a distributed TeleClaude network.
---

# Multi-Computer Setup Guide

## Phase 1: Preparation
1. **Provision Bots**: Create a unique Telegram bot for each computer via [@BotFather](https://t.me/botfather).
2. **Supergroup**: Create a Telegram supergroup, enable Topics, and add all bots as admins.
3. **Redis**: Ensure a Redis instance is accessible from all computers (required for AI-to-AI).

## Phase 2: Installation
1. **Clone & Install**: `make install && make init` on each machine.
2. **Config**:
   - `computer_name`: Set a unique shorthand (e.g., `macbook`).
   - `is_master`: Set to `true` on EXACTLY one computer.
   - `redis_url`: Point to your shared Redis instance.
   - `trusted_dirs`: Add paths you want agents to be able to access.

## Phase 3: SSH Configuration
1. **Keychain**: Set up `keychain` as described in `procedure/ssh-agent-keychain`.
2. **Key Exchange**: Ensure the master can SSH into remotes via agent forwarding.

## Phase 4: Verification
1. **Status**: `make status` on all nodes.
2. **Discovery**: In any AI session, call `teleclaude__list_computers()` to see the full network.