---
description: 'Recommended flow for delegating work using TeleClaude CLI/API commands.'
visibility: 'public'
---

# AI-to-AI Operations — Procedure

## Required reads

- @docs/project/spec/command-surface.md
- @docs/project/spec/command-contracts.md
- @docs/project/spec/session-subscriptions.md

## Goal

Delegate work to remote AI sessions safely and predictably.

## Preconditions

- Target computer is online and listed in trusted dirs.
- You have a clear task and title for the delegated session.
- Know which dispatch mechanism to use:

- **`telec sessions run`** — Dispatch worker lifecycle commands. Canonical way to start orchestrated work (build, review, fix cycles). Uses slash commands: `/next-build`, `/next-review-build`, `/next-finalize`. The fix round dispatches no command: the reviewer opens a direct conversation with the existing builder session, which applies the findings and commits. Example: `telec sessions run --command /next-build --args my-slug --path /repo/path`

- **`telec sessions start`** — Start a general-purpose session with a freeform message. Use for ad-hoc tasks, peer discussions, and non-lifecycle work.

## Steps

1. List computers to confirm the target is online.
2. List projects to select a trusted project path.
3. Dispatch the session:

- For worker lifecycle: `telec sessions run --command /next-build --args <slug> --path <path>`
- For general tasks: `telec sessions start --path <path> --agent <agent> --message "<instruction>"`

4. Follow up on the session:
   - For dispatched workers: `telec sessions tail` for status checks. Workers run autonomously — avoid unnecessary follow-ups.
   - For peer discussions: `telec sessions send <id> "<message>" --direct` establishes a linked conversation where turn-complete outputs are automatically cross-shared. Use for collaborative sessions where both agents need to see each other's output. Sever with `--close-link` when done.
   - If you dispatched the target and now want to talk to it directly, you can hold both subscriptions at once. Your dispatch-time listener is preserved; notifications are silently suppressed while the direct link is active and resume automatically when you close the link. See `project/spec/session-subscriptions` for the contract.
5. Stop caring about a target with `telec sessions unsubscribe <id>`. This is the umbrella verb: it removes any listener you hold AND closes any direct link you have with that target. Idempotent — empty state returns success. Use `--close-link` instead if you only want to end the conversation but keep passive notifications.
6. End sessions when work completes.
7. If context is near capacity, request a summary, end, and restart fresh.

## Outputs

- Delegated session running with monitoring in place.
- Session closed and cleaned up when work completes.

## Recovery

- Forgetting to end sessions — orphaned sessions consume resources and confuse monitoring.
- Polling too aggressively with `telec sessions tail` — respect the 5-minute cadence gate.
- Starting sessions on computers or project paths that aren't in `trusted_dirs` — the command will be rejected.
- Notifications appear to stop arriving while you are in a direct conversation with the same target — expected. Suppression resumes delivery on link sever.
