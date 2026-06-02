---
description: 'Guide for setting up a distributed TeleClaude network.'
id: 'project/procedure/multi-computer-setup'
scope: 'project'
type: 'procedure'
visibility: 'public'
---

# Multi Computer Setup — Procedure

## Goal

Set up a distributed TeleClaude deployment across multiple computers.

## Preconditions

- One Telegram bot token per computer.
- Redis reachable by all nodes.
- SSH key auth between every pair of computers (`~/.ssh/authorized_keys` on each peer trusts every other peer's public key). The TUI's remote-session attach runs `ssh -t {user}@{host} ...` non-interactively — no password prompts.
- Access to each machine to install and configure TeleClaude.

## Steps

1. Create a unique Telegram bot per computer.
2. Install on each machine with `make install`, then run `telec config wizard`, then `make start`.
3. Configure `computer_name`, `telegram.is_master` (exactly one master), `redis_url`, and `trusted_dirs`.
4. Configure SSH keychain using the ssh-agent-keychain procedure. Verify each peer can `ssh user@peerhost` without a prompt before continuing — the TUI's remote-attach path requires it.
5. Verify `make status` on all nodes.
6. Use `telec computers` to confirm network discovery. Each peer should appear with non-null `user`, `host`, and `tmux_binary` — these flow through the heartbeat payload (see `project/adr/0013-unified-cluster-events`).
7. From the TUI on any peer, sessions/projects/todos from every other peer appear automatically as the cluster.* events flow. No subscription action required.

## Outputs

- Multi-node TeleClaude deployment with Redis discovery working.
- Every peer's sessions, projects, and todos visible in the TUI from any peer.
- One Telegram master configured and verified.

## Recovery

- Multiple computers with `telegram.is_master: true` — causes duplicate command handling and message collisions.
- Reusing bot tokens across computers — Telegram will deliver updates to only one instance.
- Missing `trusted_dirs` entries — `telec`/API project commands won't expose projects on that computer.
- Redis unreachable — cross-computer commands silently fail; local operations still work.
- TUI remote-session attach prompts for password or fails — SSH key auth between peers is missing or not loaded into the agent (step 4). Verify with `ssh -o BatchMode=yes user@peerhost true` from a non-interactive shell.
- Peer shows in `telec computers` with `host=null` / `user=null` — that peer is running the pre-cluster-events daemon. Upgrade and restart the peer; the next heartbeat will publish full identity.
