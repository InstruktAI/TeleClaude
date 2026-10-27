---
description: 'Guide for setting up a distributed TeleClaude network.'
visibility: 'public'
---

# Multi Computer Setup — Procedure

## Goal

Set up a distributed TeleClaude deployment across multiple computers.

## Preconditions

- One Telegram bot token per computer.
- Redis reachable by all nodes.
- SSH key auth between every pair of computers (`~/.ssh/authorized_keys` on each peer trusts every other peer's public key). The TUI's remote-session attach runs `ssh -t {user}@{host} ...` non-interactively — no password prompts.
- Peer SSH identity fields used for remote attach (`user`, `host`) must contain only letters, digits, `.`, `_`, and `-`. Heartbeat ingestion rejects unsafe values before caching them.
- Access to each machine to install and configure TeleClaude.

## Steps

1. Create a unique Telegram bot per computer.
2. Install on each machine with `make install`, then run `telec config wizard`, then `make start`.
3. Configure `computer_name`, `telegram.is_master` (exactly one master), and `redis_url`, then adopt each project on that machine with `telec config project adopt` from its folder, or from the TUI's new-project action.
4. Configure SSH keychain using the ssh-agent-keychain procedure. Verify each peer can `ssh user@peerhost` without a prompt before continuing — the TUI's remote-attach path requires it.
5. Verify `make status` on all nodes.
6. Use `telec computers list` to confirm network discovery. Each peer should appear with non-null `user` and `host` from the heartbeat payload (see `local/projects/teleclaude/adr/0013-unified-cluster-events`).
7. From the TUI on any peer, **sessions** from every other peer appear automatically via the live `cluster.session.*` event stream. Projects and todos appear after the daemon's bootstrap snapshot completes (within a few seconds of connect). No subscription action required for any category.

## Outputs

- Multi-node TeleClaude deployment with Redis discovery working.
- Every peer's sessions visible in the TUI in real time; projects and todos visible after bootstrap.
- One Telegram master configured and verified.

## Recovery

- Multiple computers with `telegram.is_master: true` — causes duplicate command handling and message collisions.
- Reusing bot tokens across computers — Telegram will deliver updates to only one instance.
- A project missing from a computer's listing — it was never adopted there; run `telec config project adopt` in its folder on that computer.
- Redis unreachable — `make start` fails fast and surfaces the unreachable Redis at startup instead of reporting a healthy runtime; verify `REDIS_CLUSTER_URL` and that the cluster Redis server is reachable, then re-run `make start`.
- TUI remote-session attach prompts for password or fails — SSH key auth between peers is missing or not loaded into the agent (step 4). Verify with `ssh -o BatchMode=yes user@peerhost true` from a non-interactive shell.
- Peer shows in `telec computers` with `host=null` / `user=null` — that peer is running the pre-cluster-events daemon. Upgrade and restart the peer; the next heartbeat will publish full identity.
- Peer disappears from remote attach even though Redis is reachable — verify the peer's `user` and `host` values match the shell-safe identifier grammar `[A-Za-z0-9._-]+`. Unsafe values are rejected before cache ingestion so they cannot be interpolated into SSH/tmux commands.
- Peer shows in `telec computers list` with `tmux_binary=null` — this is by design. The peer's tmux client is resolved via the remote shell's PATH at attach time; the local-only launcher binary is not part of the cross-computer protocol.
